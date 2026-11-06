"""단계별 평가 — 정답셋(data/eval/stage_gold.json)으로 ① 의도 ② 경로 ③ API ④ 파라미터(IR) 를 따로 채점한다 (2026-11-06).

태스크셋 채점(evaluate.py)과 다른 점
  - ① 출력 칸을 모두 본다 (action · conditions · source_phrases · constraints 의 source_phrase · unresolved · injections 포함)
  - ④ 승인 → 혜정 IR 생성까지 돌려 필드마다 고정값 · 앞 단계 값 · 실행 시 입력을 채점한다
  - 판단 보류({"pending": 질문})는 맞음 · 틀림과 섞지 않고 따로 센다 — 정해야 할 것 목록으로 남긴다
  - 앞 단계가 틀리거나 판단 보류면 뒤 단계는 '앞 단계 제외'로 센다 (단독 정확도는 따로)
  - 같은 요청을 여러 번 돌려(runs) 단계마다 결과가 같은지(일치율)를 본다

단계 판정: 맞음 · 틀림 · 판단 보류(단계 전체가 미정) · 앞 단계 제외 · 해당 없음(정답에 그 단계가 없음)
"""
from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tap.evaluate import _api_name, _sel, _violations

STAGES = ("intent", "paths", "apis", "params", "final")
STAGE_KO = {"intent": "① 의도", "paths": "② 경로", "apis": "③ API", "params": "④ 파라미터", "final": "최종"}
OK, WRONG, PENDING, SKIP, NA = "맞음", "틀림", "판단 보류", "앞 단계 제외", "해당 없음"
TASK_FIELDS = ("sequence", "domain", "origin", "action", "conditions", "count", "depends_on", "source_phrases")
PATH_FIELDS = ("sequence", "domain", "graph_id", "origin", "from_state", "to_state", "start_by", "edges", "must_pass", "status")


def load_gold(path: str | Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["cases"]


# ─── 값 하나 비교 ──────────────────────────────────────────────────────────────────────

def _txt(x: Any) -> str:
    if isinstance(x, list):
        return " ".join(_txt(v) for v in x)
    return re.sub(r"^[\s\"'“”‘’]+|[\s\"'“”‘’]+$", "", "" if x is None else str(x))


def is_pending(g: Any) -> bool:
    return isinstance(g, dict) and "pending" in g


def match(g: Any, got: Any, utt: str) -> bool:
    """정답 g 와 출력 got 비교 (판단 보류는 부르는 쪽이 먼저 거른다)."""
    if isinstance(g, dict) and any(k in g for k in ("any_of", "contains", "contains_any", "in_utterance", "empty", "not_empty")):
        ok = True
        if "any_of" in g:
            ok &= any(match(v, got, utt) for v in g["any_of"])
        if "contains" in g:
            ok &= all(_txt(w) in _txt(got) for w in g["contains"])
        if "contains_any" in g:
            ok &= any(_txt(w) in _txt(got) for w in g["contains_any"])
        if g.get("in_utterance"):
            items = got if isinstance(got, list) else [got]
            ok &= bool(items) and all(_txt(v) and _txt(v) in utt for v in items)
        if g.get("empty"):
            ok &= not got
        if g.get("not_empty"):
            ok &= bool(got)
        return ok
    if isinstance(g, dict) and isinstance(got, dict):
        return _sel(g) == _sel(got)
    if isinstance(g, list) and isinstance(got, list):
        return len(g) == len(got) and all(match(a, b, utt) for a, b in zip(g, got))
    if g is None or got is None or isinstance(g, (bool, int, float)) and not isinstance(g, str):
        return g == got
    return _txt(g) == _txt(got)


class Fields:
    """필드마다 판정을 모은다 — stage · key(묶음용 이름) · where(케이스 안 위치)."""

    def __init__(self, stage: str, utt: str):
        self.stage, self.utt, self.rows = stage, utt, []

    def add(self, key: str, where: str, g: Any, got: Any, why: str | None = None) -> None:
        if is_pending(g):
            self.rows.append({"stage": self.stage, "key": key, "where": where, "verdict": PENDING, "question": g["pending"], "got": got})
            return
        ok = match(g, got, self.utt)
        row = {"stage": self.stage, "key": key, "where": where, "verdict": OK if ok else WRONG, "got": got}
        if not ok:
            row["want"] = {k: v for k, v in g.items() if k != "_note"} if isinstance(g, dict) else g
            if why:
                row["why"] = why
        self.rows.append(row)

    def wrong(self, key: str, where: str, why: str, got: Any = None, want: Any = None) -> None:
        row = {"stage": self.stage, "key": key, "where": where, "verdict": WRONG, "why": why, "got": got}
        if want is not None:
            row["want"] = {k: v for k, v in want.items() if k != "_note"} if isinstance(want, dict) else want
        self.rows.append(row)


# ─── 단계별 채점 ──────────────────────────────────────────────────────────────────────

def _constraints(F: Fields, where: str, gold: list[dict[str, Any]], got: list[dict[str, Any]]) -> None:
    left = list(got)
    for i, g in enumerate(gold, 1):
        hit = next((c for c in left if match(g["value"], c.get("value"), F.utt)), None) if not is_pending(g.get("value")) else None
        if hit is None:
            F.wrong("constraints", f"{where}.constraints[{i}]", f"조건 없음 — 값 {g.get('value')}")
            continue
        left.remove(hit)
        F.add("constraints.value", f"{where}.constraints[{hit.get('name')}].value", g["value"], hit.get("value"))
        for k in ("name", "role", "source_phrase"):
            if k in g:
                F.add(f"constraints.{k}", f"{where}.constraints[{hit.get('name')}].{k}", g[k], hit.get(k))
    for c in left:
        F.wrong("constraints", f"{where}.constraints[{c.get('name')}]", "정답에 없는 조건", c)


def score_intent(g: dict[str, Any], tp: dict[str, Any], utt: str) -> list[dict[str, Any]]:
    F = Fields("intent", utt)
    F.add("original_question", "original_question", utt, tp.get("original_question"))
    gt, tasks = g.get("tasks") or [], tp.get("tasks") or []
    F.add("업무 수", "tasks", len(gt), len(tasks))
    for e, t in zip(gt, tasks):
        w = f"tasks[{e.get('sequence', '?')}]"
        for k in TASK_FIELDS:
            if k in e:
                F.add(k, f"{w}.{k}", e[k], t.get(k))
        if "constraints" in e:
            if is_pending(e["constraints"]):
                F.add("constraints", f"{w}.constraints", e["constraints"], t.get("constraints"))
            else:
                _constraints(F, w, e["constraints"], t.get("constraints") or [])
    for k in ("unresolved", "injections"):
        if k in g:
            F.add(k, k, g[k], tp.get(k) or [])
    return F.rows


def score_paths(g: list[dict[str, Any]], pp: dict[str, Any], utt: str) -> list[dict[str, Any]]:
    F = Fields("paths", utt)
    paths = pp.get("paths") or []
    F.add("경로 수", "paths", len(g), len(paths))
    for e, p in zip(g, paths):
        for k in PATH_FIELDS:
            if k in e:
                got = [s["edge"] for s in p.get("steps") or []] if k == "edges" else p.get(k)
                F.add(k, f"paths[{e.get('sequence', '?')}].{k}", e[k], got)
    return F.rows


def score_apis(g: list[dict[str, Any]], sel: dict[str, Any], gate: dict[str, Any] | None, utt: str) -> list[dict[str, Any]]:
    F = Fields("apis", utt)
    rows = {f"{r['path_sequence']}-{r['step']}": r for r in sel.get("api_selection_results") or []}
    tiers = {s["key"]: s.get("tier") for s in (gate or {}).get("steps") or []}
    F.add("단계 수", "apis", len(g), len(rows))
    for e in g:
        r = rows.get(e["step"])
        if r is None:
            F.wrong("단계", e["step"], "그 단계가 없음")
            continue
        picked = r.get("selected") or {}
        F.add("api", f"{e['step']}.api", e.get("api"), _api_name(picked.get("api_id")))
        if "selector" in e:
            F.add("selector", f"{e['step']}.selector", e["selector"], picked.get("selector") or {})
        if "tier" in e:
            F.add("tier", f"{e['step']}.tier", e["tier"], tiers.get(e["step"]))
    return F.rows


def score_params(g: dict[str, Any], ir: dict[str, Any] | None, utt: str) -> list[dict[str, Any]]:
    """ir = compact_ir() 결과. 필드는 요청 경로 끝 이름(parameter_path) 기준 — IR 이 붙인 이름이 달라도 실제 넣는 곳으로 본다."""
    F = Fields("params", utt)
    if ir is None or ir.get("error"):
        F.wrong("IR 생성", "ir", f"IR 없음 — {(ir or {}).get('error') or '승인 · 넘기기 전에 멈춤'}")
        return F.rows
    for sid, want in g.items():
        step = (ir.get("steps") or {}).get(sid)
        if step is None:
            F.wrong("단계", sid, "IR 에 그 단계가 없음")
            continue
        got = step["params"]
        for field, spec in want.items():
            if field.startswith("_"):
                continue
            w, p = f"{sid}.{field}", got.get(field)
            if is_pending(spec):
                F.add("판단 보류 필드", w, spec, p)
                continue
            src = spec.get("source")
            if src == "empty":
                F.add("empty", w, True, not p or p["source"] not in ("fixed", "bind"), "넣으면 안 되는 값을 넣음")
            elif p is None:
                F.wrong(f"{src} 빠짐", w, "필드를 채우지 않음", want=spec)
            elif src == "run_input":
                F.add("run_input", w, {"any_of": ["run_input", "unresolved"]}, p["source"])
            else:
                F.add(f"{src}.source", f"{w}.source", src, p["source"])
                if src == "fixed" and "value" in spec:
                    F.add("fixed.value", f"{w}.value", spec["value"], p.get("value"))
                if src == "bind" and "from" in spec:
                    F.add("bind.from", f"{w}.from", spec["from"], p.get("from"), "앞 단계의 다른 값을 연결")
        if want.get("_others") == "empty":
            for field, p in got.items():
                if field not in want and p["source"] in ("fixed", "bind"):
                    F.wrong("정답에 없는 값", f"{sid}.{field}", "정답에 없는 필드에 값을 넣음", p)
    return F.rows


def score_final(g: dict[str, Any], out: dict[str, Any], case: dict[str, Any], utt: str) -> list[dict[str, Any]]:
    F = Fields("final", utt)
    final = out.get("final_status")
    gate = (out.get("gate") or {}).get("status")
    if "status" in g:
        F.add("status", "final.status", {"any_of": g["status"]}, final)
    if "gate" in g:
        F.add("gate", "final.gate", {"any_of": g["gate"]}, gate)
    if case.get("forbid"):
        v = _violations(case["forbid"], {"tasks": (out.get("tasks") or {}).get("tasks") or [],
                                         "paths": (out.get("paths") or {}).get("paths") or [],
                                         "apis": out.get("apis") or {}, "gate": out.get("gate")})
        if v:
            F.wrong("인젝션 뚫림", "forbid", "; ".join(v))
        else:
            F.rows.append({"stage": "final", "key": "인젝션 막힘", "where": "forbid", "verdict": OK, "got": None})
    return F.rows


def _verdict(rows: list[dict[str, Any]]) -> str:
    return WRONG if any(r["verdict"] == WRONG for r in rows) else OK


def _stage_rows(s: str, g: Any, out: dict[str, Any], case: dict[str, Any]) -> list[dict[str, Any]]:
    utt = case["utterance"]
    have = {"intent": out.get("tasks"), "paths": out.get("paths"), "apis": out.get("apis"),
            "params": out.get("ir") if out.get("tasks") else None, "final": out}.get(s)
    if have is None and s != "params":
        return [{"stage": s, "key": "결과 없음", "where": s, "verdict": WRONG, "why": out.get("error") or "앞에서 멈춤", "got": None}]
    if s == "intent":
        return score_intent(g, have, utt)
    if s == "paths":
        return score_paths(g, have, utt)
    if s == "apis":
        return score_apis(g, have, out.get("gate"), utt)
    if s == "params":
        return score_params(g, have, utt)
    return score_final(g, out, case, utt)


def score(case: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """한 번 실행한 결과(out) 채점. stages[단계] = {verdict(앞 단계 반영), alone(그 단계만), fields}.

    정답이 여럿이면 단계 정답을 {"one_of": [정답1, 정답2 …]} 로 적는다 — 처음 나온 단계에서 가장 덜 틀린 정답을 고르고,
    뒤 단계의 one_of 도 같은 번호를 쓴다 (예: 출발 상태가 다르면 경로 · API · 파라미터가 함께 달라짐).
    """
    exp, utt = case.get("expect") or {}, case["utterance"]
    stages: dict[str, Any] = {}
    blocked_by = None                                   # 앞 단계에서 틀림 · 판단 보류 · 결과 없음
    variant = None                                      # one_of 에서 고른 정답 번호
    for s in STAGES:
        g = exp.get(s)
        if g is None:                                   # 판단 보류 뒤라 정답을 *_if_supported 로만 적어 둔 단계는 '앞 단계 제외'
            v = SKIP if blocked_by and f"{s}_if_supported" in exp else NA
            stages[s] = {"verdict": v, "alone": NA, "fields": [], **({"skipped_because": blocked_by} if v == SKIP else {})}
            continue
        if is_pending(g):
            stages[s] = {"verdict": PENDING, "alone": PENDING, "fields": [], "question": g["pending"]}
            blocked_by = blocked_by or f"{STAGE_KO[s]} 판단 보류"
            continue
        picked = None
        if isinstance(g, dict) and "one_of" in g:
            alts = g["one_of"]
            if variant is not None and variant < len(alts):
                picked, rows = variant, _stage_rows(s, alts[variant], out, case)
            else:
                tries = [_stage_rows(s, x, out, case) for x in alts]
                picked = min(range(len(alts)), key=lambda i: sum(r["verdict"] == WRONG for r in tries[i]))
                rows, variant = tries[picked], picked
        else:
            rows = _stage_rows(s, g, out, case)
        alone = _verdict(rows)
        verdict = alone if s == "final" or blocked_by is None else SKIP
        stages[s] = {"verdict": verdict, "alone": alone, "fields": rows, **({"variant": picked} if picked is not None else {})}
        if s != "final" and verdict == WRONG:
            blocked_by = f"{STAGE_KO[s]} 틀림"
        if verdict == SKIP:
            stages[s]["skipped_because"] = blocked_by
    first = next((STAGE_KO[s] for s in STAGES if stages[s]["verdict"] == WRONG), None)
    return {"id": case["id"], "category": case["category"], "utterance": utt, "stages": stages, "first_fail": first}


# ─── 실행 ────────────────────────────────────────────────────────────────────────────

def compact_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """혜정 IR → 단계마다 {요청 필드: {source, origin, value | from}} (원본은 data/out/scenario_ir_drafts)."""
    steps = {}
    for task in ir.get("tasks") or []:
        for s in task.get("steps") or []:
            binds = {b["to_parameter_path"]: b["from"] for b in s.get("bindings") or []}
            params = {}
            for i in s.get("inputs") or []:
                key = (i.get("parameter_path") or i.get("field") or "?").rsplit(".", 1)[-1]
                v = {"source": i["source"], "origin": i.get("origin")}
                if i["source"] == "fixed":
                    v["value"] = i.get("value")
                b = binds.get(i.get("parameter_path"))
                if b:
                    v["from"] = f"{b['from_step_id']}.{(b.get('response_path') or '').rsplit('/', 1)[-1]}"
                if i.get("field") and i["field"] != key:
                    v["ir_field"] = i["field"]
                if i.get("reason"):
                    v["reason"] = i["reason"][:200]                 # IR 이 그렇게 넣은 이유 (실패 상세에 씀)
                params[key] = v
            steps[s["step_id"]] = {"api": _api_name(s["api"]["api_id"]), "params": params,
                                   "outputs": [o["name"] for o in s.get("outputs") or []]}
    return {"status": ir.get("status"), "steps": steps,
            "unresolved": [str(u.get("reason"))[:300] for u in ir.get("unresolved") or [] if isinstance(u, dict)]}


def make_ir(root: Path, stop_retry: bool = True) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """analyze_select 결과 → 승인 → 혜정 형식 승인본 → IR 생성. 화면(/api/approve → IR 생성)과 같은 길."""
    def run(r: dict[str, Any]) -> dict[str, Any]:
        from tap.apis.gate import approve
        from tap.ir.draft_build import fixed_plan, generate
        from tap.ir.handoff import hyejung_approved, missing_materials, save_hyejung_approved
        g = r["gate"]
        ap = approve(g, "평가", scenario=True, steps=list(g.need_steps))
        data = hyejung_approved(r["tasks"], r["paths"], r["apis"], g, ap, {"trace": r.get("trace_file")})
        missing = missing_materials(root, data, fixed_plan(json.loads(json.dumps(data))))
        if missing:
            return {"error": "IR 자료 없음: " + "; ".join(missing)}
        t0 = time.monotonic()
        try:
            res = generate(root, save_hyejung_approved(root, data), None, generation_options={"stop_retry": stop_retry})
        except Exception as e:                          # IR 정지조건 (예산 · 토큰 부족 등)도 결과다
            return {"error": f"{type(e).__name__}: {str(e)[:300]}", "seconds": round(time.monotonic() - t0, 1)}
        ir = json.loads((root / res["file"]).read_text(encoding="utf-8"))
        u = res.get("usage") or {}
        return {**compact_ir(ir), "file": res["file"], "seconds": round(time.monotonic() - t0, 1),
                "llm_calls": u.get("llm_calls"), "tokens": u.get("total_tokens"), "cost_usd": u.get("cost_usd")}
    return run


def _stage_cost(trace: dict[str, Any] | None) -> dict[str, Any]:
    calls = (trace or {}).get("calls") or []
    by: dict[str, Any] = {}
    for c in calls:
        s = by.setdefault(c["stage"], {"llm_calls": 0, "cost_usd": 0.0, "ms": 0})
        s["llm_calls"] += 1
        s["cost_usd"] = round(s["cost_usd"] + (c.get("cost_usd") or 0), 6)
        s["ms"] += c.get("ms") or 0
    t = (trace or {}).get("totals") or {}
    return {"by_stage": by, "ms": t.get("ms"), "cost_usd": t.get("cost_usd"), "llm_calls": t.get("llm_calls")}


def run_once(case: dict[str, Any], analyze: Callable[[str], dict[str, Any]], ir: Callable | None) -> dict[str, Any]:
    """①②③ (+ 승인 게이트를 통과하면 ④ IR). 멈춘 것도 결과로 남긴다."""
    out: dict[str, Any] = {"tasks": None, "paths": None, "apis": None, "gate": None, "ir": None, "error": None}
    try:
        r = analyze(case["utterance"])
        out["trace_file"] = r.get("trace_file")
        out.update(tasks=r["tasks"].model_dump(), paths=r["paths"].dump(), apis=r["apis"].dump(),
                   gate=r["gate"].model_dump(), final_status=r["apis"].status, cost=_stage_cost(r["trace"].to_dict()))
        if ir and r["gate"].status in ("자동", "승인 필요"):
            out["ir"] = ir(r)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["final_status"] = "거절(검사)" if out["error"].startswith("GoalError") else \
            "중단" if out["error"].startswith(("BudgetExceeded", "Stopped")) else "오류"
        tr = getattr(e, "trace", None)
        out["cost"] = _stage_cost(tr.to_dict() if tr is not None else None)
    return out


def signature(stage: str, out: dict[str, Any]) -> str:
    """같은 요청을 여러 번 돌렸을 때 그 단계 결과가 같은지 — 자유 글(action · conditions 등)은 뺀 핵심만."""
    if stage == "intent":
        tp = out.get("tasks") or {}
        x = [(t["domain"], t["origin"], t["count"], sorted((c["name"], c["value"], c["role"]) for c in t["constraints"]))
             for t in tp.get("tasks") or []], bool(tp.get("injections"))
    elif stage == "paths":
        x = [(p["graph_id"], p["from_state"], p["to_state"], p["start_by"], [s["edge"] for s in p.get("steps") or []], p["status"])
             for p in (out.get("paths") or {}).get("paths") or []]
    elif stage == "apis":
        x = [(r["path_sequence"], r["step"], _api_name((r.get("selected") or {}).get("api_id")), _sel((r.get("selected") or {}).get("selector")))
             for r in (out.get("apis") or {}).get("api_selection_results") or []]
    elif stage == "params":
        ir = out.get("ir") or {}
        x = ir.get("error") and "error" or {sid: {k: (v["source"], _txt(v.get("value")), v.get("from")) for k, v in s["params"].items()}
                                            for sid, s in (ir.get("steps") or {}).items()}
    else:
        x = out.get("final_status"), (out.get("gate") or {}).get("status")
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)


# ─── 요약 · 보고서 ─────────────────────────────────────────────────────────────────────

def summarize(cases: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    """runs = [{id, run, out, score}] — 모든 (케이스, 회차)를 한 번씩 센다."""
    table = {}
    for s in STAGES:
        c = Counter(r["score"]["stages"][s]["verdict"] for r in runs)
        alone = [r["score"]["stages"][s]["alone"] for r in runs if r["score"]["stages"][s]["alone"] in (OK, WRONG)]
        table[STAGE_KO[s]] = {OK: c[OK], WRONG: c[WRONG], PENDING: c[PENDING], SKIP: c[SKIP], NA: c[NA],
                              "단독 맞음": f"{alone.count(OK)}/{len(alone)}"}
    fields: dict[str, Counter] = {}
    causes: dict[str, dict[str, Any]] = {}
    pending: dict[tuple, str] = {}
    for r in runs:
        for s in STAGES:
            st = r["score"]["stages"][s]
            if st.get("question"):
                pending[(r["id"], STAGE_KO[s], "(단계 전체)")] = st["question"]
            for f in st["fields"]:
                k = f"{STAGE_KO[s]} {f['key']}"
                fields.setdefault(k, Counter())[f["verdict"]] += 1
                if f["verdict"] == PENDING:
                    pending[(r["id"], STAGE_KO[s], f["where"])] = f["question"]
                own = st["verdict"] == WRONG and (s != "final" or r["score"]["first_fail"] == STAGE_KO["final"])
                if f["verdict"] == WRONG and own:          # 앞 단계 오류가 번진 것(앞 단계 제외 · 최종)은 원인으로 세지 않음
                    c = causes.setdefault(k, {"건수": 0, "케이스": [], "예": None})
                    c["건수"] += 1
                    if r["id"] not in c["케이스"]:
                        c["케이스"].append(r["id"])
                    c["예"] = c["예"] or (f"{r['id']} {f['where']}: " + (f"{f['why']} · " if f.get("why") else "")
                                         + f"출력 {json.dumps(f.get('got'), ensure_ascii=False)[:100]}"
                                         + (f" · 정답 {json.dumps(f['want'], ensure_ascii=False)[:80]}" if "want" in f else ""))
    funnel = Counter(r["score"]["first_fail"] or "통과 (틀린 단계 없음)" for r in runs)
    stability = {}
    by_case: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        by_case.setdefault(r["id"], []).append(r)
    if any(len(v) > 1 for v in by_case.values()):
        for cid, rs in by_case.items():
            stability[cid] = {STAGE_KO[s]: round(Counter(signature(s, r["out"]) for r in rs).most_common(1)[0][1] / len(rs), 2)
                              for s in STAGES if rs[0]["score"]["stages"][s]["verdict"] != NA}
    sel_cost = [r["out"].get("cost") or {} for r in runs]
    irs = [r["out"]["ir"] for r in runs if r["out"].get("ir") and not r["out"]["ir"].get("error")]
    mean = lambda xs: round(statistics.mean(xs), 4) if xs else None
    cost = {"①②③ 요청당 비용 평균_usd": mean([c["cost_usd"] for c in sel_cost if c.get("cost_usd") is not None]),
            "①②③ 요청당 지연 평균_ms": int(statistics.mean([c["ms"] for c in sel_cost if c.get("ms")])) if any(c.get("ms") for c in sel_cost) else None,
            "④ IR 건수": len(irs), "④ IR 비용 평균_usd": mean([x["cost_usd"] for x in irs if x.get("cost_usd") is not None]),
            "④ IR 지연 평균_s": mean([x["seconds"] for x in irs if x.get("seconds")]),
            "합계_usd": round(sum(c.get("cost_usd") or 0 for c in sel_cost) + sum(x.get("cost_usd") or 0 for x in irs), 4)}
    stage_cost: dict[str, dict[str, float]] = {}
    for c in sel_cost:
        for k, v in (c.get("by_stage") or {}).items():
            s = stage_cost.setdefault(k, {"호출": 0, "비용_usd": 0.0, "ms": 0})
            s["호출"] += v["llm_calls"]
            s["비용_usd"] = round(s["비용_usd"] + v["cost_usd"], 6)
            s["ms"] += v["ms"]
    return {"케이스": len(cases), "실행": len(runs), "단계별": table,
            "필드별": {k: dict(v) for k, v in sorted(fields.items())},
            "오류 종류": dict(sorted(causes.items(), key=lambda kv: -kv[1]["건수"])),
            "처음 틀린 단계": dict(funnel), "일치율": stability, "비용 · 지연": cost, "단계별 LLM": stage_cost,
            "판단 보류": [{"case": k[0], "stage": k[1], "where": k[2], "question": q} for k, q in sorted(pending.items())]}


def _mark(v: str) -> str:
    return {OK: "○", WRONG: "✕", PENDING: "보류", SKIP: "-", NA: ""}.get(v, v)


def report_md(summary: dict[str, Any], runs: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    s = summary
    L = [f"# 단계별 평가 — {meta['at']}", "",
         f"정답셋 {meta['gold']} · 케이스 {s['케이스']}개 × {meta['runs']}회 = {s['실행']}번 · 모델 {meta.get('model') or '기본'} · "
         f"중지조건 · 재시도 {'켬' if meta['stop_retry'] else '끔'} · IR {'함' if meta['ir'] else '안 함'}", "",
         "## 1. 단계별 결과", "",
         f"| 단계 | {OK} | {WRONG} | {PENDING} | {SKIP} | {NA} | 단독 맞음 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {k} | {v[OK]} | {v[WRONG]} | {v[PENDING]} | {v[SKIP]} | {v[NA]} | {v['단독 맞음']} |" for k, v in s["단계별"].items()]
    L += ["", f"- {PENDING}: 정답이 아직 정해지지 않은 단계 — 맞음 · 틀림에 넣지 않음",
          f"- {SKIP}: 앞 단계가 틀렸거나 판단 보류라 세지 않음. '단독 맞음'은 앞 단계와 상관없이 그 단계만 본 것", "",
          "## 2. 어디서 떨어졌나", "", "| 케이스 | " + " | ".join(STAGE_KO[x] for x in STAGES) + " | 처음 틀린 단계 |",
          "|---|" + "---|" * (len(STAGES) + 1)]
    for r in runs:
        tag = r["id"] + (f" #{r['run']}" if meta["runs"] > 1 else "")
        L.append(f"| {tag} | " + " | ".join(_mark(r["score"]["stages"][x]["verdict"]) for x in STAGES) + f" | {r['score']['first_fail'] or ''} |")
    L += ["", "| 처음 틀린 단계 | 건수 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in s["처음 틀린 단계"].items()]
    L += ["", "## 3. 오류 종류 (그 단계에서 처음 틀린 것만 — 앞 단계 오류가 번진 것은 뺌)", "", "| 단계 · 필드 | 건수 | 케이스 | 예 |", "|---|---|---|---|"]
    L += [f"| {k} | {v['건수']} | {', '.join(v['케이스'])} | {v['예'].replace('|', '/')} |" for k, v in s["오류 종류"].items()] or ["| 없음 | | | |"]
    L += ["", "## 4. 필드별", "", f"| 단계 · 필드 | {OK} | {WRONG} | {PENDING} |", "|---|---|---|---|"]
    L += [f"| {k} | {v.get(OK, 0)} | {v.get(WRONG, 0)} | {v.get(PENDING, 0)} |" for k, v in s["필드별"].items()]
    if s["일치율"]:
        L += ["", "## 5. 일치율 (같은 요청을 여러 번 — 가장 많이 나온 결과의 비율)", "",
              "| 케이스 | " + " | ".join(STAGE_KO[x] for x in STAGES) + " |", "|---|" + "---|" * len(STAGES)]
        L += [f"| {cid} | " + " | ".join(str(v.get(STAGE_KO[x], "")) for x in STAGES) + " |" for cid, v in s["일치율"].items()]
    c = s["비용 · 지연"]
    L += ["", "## 6. 비용 · 지연", "", "| 항목 | 값 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in c.items()]
    L += ["", "| LLM 단계 | 호출 | 비용 | 시간 |", "|---|---|---|---|"]
    L += [f"| {k} | {v['호출']} | ${v['비용_usd']:.4f} | {v['ms']}ms |" for k, v in s["단계별 LLM"].items()]
    L += ["", "## 7. 판단 보류 — 정해야 할 것", "", "| 케이스 | 단계 | 위치 | 질문 |", "|---|---|---|---|"]
    seen = set()
    for p in s["판단 보류"]:
        if (p["case"], p["question"]) not in seen:
            seen.add((p["case"], p["question"]))
            L.append(f"| {p['case']} | {p['stage']} | {p['where']} | {p['question']} |")
    L += ["", "## 8. 실패 상세 — 틀린 칸 · 시스템이 남긴 이유 · 파일", ""]
    L += failure_details(runs, meta["runs"] > 1) or ["틀린 케이스 없음"]
    return "\n".join(L) + "\n"


def _j(x: Any, n: int = 160) -> str:
    t = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return (t if len(t) <= n else t[:n] + "…").replace("|", "/").replace("\n", " ")


def _reasons(stage: str, out: dict[str, Any], fields: list[dict[str, Any]]) -> list[str]:
    """그 단계에서 시스템이 스스로 남긴 설명 — 왜 그렇게 골랐는지 · 왜 멈췄는지."""
    tp, pp, ap, ir = out.get("tasks") or {}, out.get("paths") or {}, out.get("apis") or {}, out.get("ir") or {}
    R = []
    if stage == "intent":
        for t in tp.get("tasks") or []:
            R.append(f"{t['sequence']}번 업무: {t['domain']} · {t['origin']} · '{t['action']}' · {t['count']}건 · 조건 "
                     + (", ".join(f"{c['name']}={c['value']}({c['role']})" for c in t["constraints"]) or "없음"))
            R.append(f"  conditions: {_j(t['conditions'])}")
        R += [f"unresolved: {_j(u)}" for u in tp.get("unresolved") or []]
    elif stage == "paths":
        for p in pp.get("paths") or []:
            R.append(f"{p['sequence']}번 경로: 그래프 {p['graph_id']} · {p['from_state']} → {p['to_state']} · {p['status']}"
                     + (f" · 목표 근거 {_j(p.get('to_state_reason'), 100)}" if p.get("to_state_reason") else ""))
            R += [f"  notes: {_j(n)}" for n in p.get("notes") or []]
        R += [f"unresolved: {_j(u)}" for u in pp.get("unresolved") or []]
    elif stage == "apis":
        for r in ap.get("api_selection_results") or []:
            picked = r.get("selected") or {}
            R.append(f"{r['path_sequence']}-{r['step']} {r.get('edge')}: {_api_name(picked.get('api_id')) or '없음'} "
                     f"{_sel(picked.get('selector')) or ''} · {r.get('selection_status')} · {r.get('selected_by') or '-'} — {_j(r.get('selection_reason'), 140)}")
        R += [f"unresolved: {_j(u.get('reason') if isinstance(u, dict) else u)}" for u in ap.get("unresolved") or []]
    elif stage == "params":
        if ir.get("error"):
            R.append(f"IR 오류: {_j(ir['error'], 300)}")
        for f in fields:
            sid, _, field = f["where"].partition(".")
            p = ((ir.get("steps") or {}).get(sid) or {}).get("params", {}).get(field.split(".")[0])
            if p and p.get("reason"):
                R.append(f"{sid}.{field.split('.')[0]}: {_j(p['reason'], 180)}")
        R += [f"IR unresolved: {_j(u, 200)}" for u in ir.get("unresolved") or []]
    else:
        R += [f"게이트 차단: {_j(b)}" for b in (out.get("gate") or {}).get("blocked") or []]
        R += [f"멈춤: {_j(out['error'], 300)}"] if out.get("error") else []
    return R


def failure_details(runs: list[dict[str, Any]], many: bool) -> list[str]:
    """케이스마다 처음 틀린 단계(와 그 뒤 직접 틀린 단계)의 틀린 칸 + 시스템이 남긴 이유 + IR · 트레이스 파일."""
    L = []
    for r in runs:
        sc, out = r["score"], r["out"]
        if not sc["first_fail"]:
            continue
        L += [f"### {r['id']}" + (f" #{r['run']}" if many else "") + f" — 처음 틀린 단계 {sc['first_fail']}", "",
              f"요청: {r['score']['utterance']}", ""]
        for s in STAGES:
            st = sc["stages"][s]
            if st["verdict"] != WRONG or (s == "final" and sc["first_fail"] != STAGE_KO["final"]):
                continue
            bad = [f for f in st["fields"] if f["verdict"] == WRONG]
            L += [f"**{STAGE_KO[s]}** — 틀린 칸 {len(bad)}개" + (f" (정답 {st['variant'] + 1}번 기준)" if "variant" in st else ""), "",
                  "| 칸 | 출력 | 정답 | 이유 |", "|---|---|---|---|"]
            L += [f"| {f['where']} | {_j(f.get('got'), 80)} | {_j(f.get('want'), 80) if 'want' in f else ''} | {_j(f.get('why') or '', 60)} |" for f in bad]
            why = _reasons(s, out, bad)
            if why:
                L += ["", "시스템이 남긴 이유:", ""] + [f"- {w}" for w in why]
            L.append("")
        files = [f"IR {out['ir']['file']}" for _ in [0] if (out.get("ir") or {}).get("file")] + \
                [f"트레이스 {out['trace_file']}" for _ in [0] if out.get("trace_file")]
        if files:
            L += ["파일: " + " · ".join(files), ""]
    return L


def save(summary: dict[str, Any], runs: list[dict[str, Any]], meta: dict[str, Any], directory: str | Path) -> tuple[Path, Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d-%H%M%S")
    j, m = d / f"{stem}.json", d / f"{stem}.md"
    j.write_text(json.dumps({"meta": meta, "summary": summary, "runs": runs}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    m.write_text(report_md(summary, runs, meta), encoding="utf-8")
    return j, m


def rescore(saved: dict[str, Any], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """저장된 실행 결과를 지금 정답셋으로 다시 채점 — LLM 을 다시 부르지 않는다 (정답을 고친 뒤)."""
    by = {c["id"]: c for c in cases}
    return [{**r, "score": score(by[r["id"]], r["out"])} for r in saved["runs"] if r["id"] in by]
