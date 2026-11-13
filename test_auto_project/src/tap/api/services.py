"""서버 처리 로직 — HTTP 와 무관한 함수 (docs/fastapi.md). 라우터(tap.api.routers)가 부른다.

예전 src/tap/ui/serve.py 의 모듈 함수와 처리기 안의 로직을 그대로 옮겼다 (2026-11-12, FastAPI 전환). 처리 순서 · 검사 · 저장 위치 · 응답 칸은 바꾸지 않는다.
테스트가 바꿔 끼우는 함수(tap.ir.draft_build.generate 등)는 함수 안에서, 부를 때 가져온다.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from tap.ir.draft_build import IR_INPUTS
from tap.ui.export import ui_data, write_ui_data
from tap.ui.preprocessing import save_preprocessing_baseline

Emit = Callable[[dict[str, Any]], None]


def scenario_ir_log_summaries(root: Path) -> list[dict]:
    """Summarize every persisted scenario-IR JSONL run without exposing prompts."""
    folder = root / 'data/out/scenario_ir_logs'
    summaries = []
    if not folder.is_dir():
        return summaries
    for file in folder.glob('IRRUN-*.jsonl'):
        start = None
        latest_usage = {}
        budget = None
        budget_usage = {}
        budget_reason = None
        request_turns = set()
        request_count = attempt_count = 0
        status = '미완료'
        last_recorded_at = None
        duration = 0.0
        try:
            with file.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    kind = event.get('event')
                    budget = event.get('budget') or budget
                    budget_usage = event.get('budget_usage') or budget_usage
                    budget_reason = event.get('budget_reason') or event.get('reason_code') or budget_reason
                    if kind == 'generation_start':
                        start = event
                    if kind == 'llm_request':
                        request_count += 1
                        if event.get('turn') is not None:
                            request_turns.add(event['turn'])
                    if kind == 'llm_attempt_start':
                        attempt_count += 1
                    usage = event.get('usage')
                    if isinstance(usage, dict):
                        for key, value in usage.items():
                            if isinstance(value, (int, float)):
                                latest_usage[key] = max(latest_usage.get(key, value), value)
                    recorded = event.get('recorded_at')
                    if recorded:
                        last_recorded_at = recorded
                    if isinstance(event.get('run_elapsed_seconds'), (int, float)):
                        duration = max(duration, event['run_elapsed_seconds'])
                    if kind == 'generation_complete':
                        status = '완료'
                        result_usage = (event.get('result') or {}).get('usage')
                        if isinstance(result_usage, dict):
                            latest_usage.update({k:v for k,v in result_usage.items()
                                                 if isinstance(v, (int,float))})
                        result_duration = (event.get('result') or {}).get('usage', {}).get('elapsed_seconds')
                        if isinstance(result_duration, (int,float)):
                            duration = max(duration, result_duration)
                    elif kind == 'generation_error':
                        status = '실패'
                    elif kind == 'recovery_stopped':
                        status = '중단'
            if start is None:
                continue
            if not duration and last_recorded_at and start.get('recorded_at'):
                try:
                    duration = max(0.0, (datetime.fromisoformat(last_recorded_at) -
                                          datetime.fromisoformat(start['recorded_at'])).total_seconds())
                except (TypeError, ValueError):
                    pass
            if budget is None and isinstance(start.get('config'),dict):
                c=start['config']
                budget=dict(version='legacy_fixed_v1', limits=dict(llm_calls=c.get('max_turns'),tokens=c.get('max_tokens'),seconds=c.get('max_seconds')))
            attempts = max(attempt_count, request_count)
            calls = max(int(latest_usage.get('llm_calls', 0)), attempts)
            options = start.get('options')
            if options is None and start.get('execution_mode') in ('basic', 'validated'):
                options = {'stop_retry': start['execution_mode'] == 'validated',
                           'kb_rag': False, 'dependency_projection': False}
            summaries.append({
                'run_id': start.get('run_id', file.stem), 'filename': file.name,
                'started_at': start.get('recorded_at'), 'options': options,
                'status': status, 'duration_seconds': round(duration, 3),
                'budget': budget, 'budget_usage': budget_usage, 'budget_reason':budget_reason,
                'step_count': (budget or {}).get('step_count'),
                'embedding_calls': latest_usage.get('embedding_calls'),
                'model_calls': budget_usage.get('llm_calls',calls), 'turns': len(request_turns),
                'input_tokens': int(latest_usage.get('input_tokens', 0)),
                'output_tokens': int(latest_usage.get('output_tokens', 0)),
                'embedding_tokens': int(latest_usage.get('embedding_tokens', 0)),
                'total_tokens': int(latest_usage.get('total_tokens', 0)),
            })
        except OSError:
            continue
    summaries.sort(key=lambda row: row.get('started_at') or '', reverse=True)
    return summaries


def rebuild(root: Path) -> dict:
    """1단계 산출물을 다시 만든다 — 화면 규칙까지 합쳐서. 잘못된 규칙이면 OverrideError."""
    from tap.cli import build
    return build(root / "data/specs/hmall-openapi.json", root / "data/out", root / "data/config/domains.yaml",
                 root / "data/config/services.yaml", root / "data/config/overrides.yaml",
                 rules_cfg=root / "data/config/rules.ui.yaml")


def save_rule(root: Path, rule: dict) -> dict:
    """규칙을 넣고 다시 빌드. 빌드가 실패하면 규칙 파일을 되돌린다."""
    from tap.catalog.rules import add_rule, load_rules, save_rules
    path = root / "data/config/rules.ui.yaml"
    before = load_rules(path)
    save_rules(path, add_rule(before, rule))
    try:
        return rebuild(root)
    except Exception:
        save_rules(path, before)
        raise


def delete_rule(root: Path, rid: int) -> dict:
    from tap.catalog.rules import load_rules, save_rules
    path = root / "data/config/rules.ui.yaml"
    save_rules(path, [r for r in load_rules(path) if int(r.get("id", 0)) != int(rid)])
    return rebuild(root)


def _stamp() -> tuple[str, str]:
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%Y%m%d-%H%M%S-%f")[:-3], now.strftime("%Y-%m-%d %H:%M")


def _registered_path(root: Path, sid: str) -> Path:
    p = root / "data/registered" / (re.sub(r"[^A-Za-z0-9\-]", "", str(sid)) + ".json")
    if not p.exists():
        raise ValueError(f"없는 시나리오: {sid}")
    return p


def register_scenario(root: Path, body: dict, pending: dict) -> dict:
    """최종 등록 화면 — 승인하고 등록한다 (2026-11-12). 승인 판단은 서버가 계산한 게이트로 (화면 값은 믿지 않는다).

    IR 은 승인 전에 검토 전 초안(review-*.json)으로 만들었다 → 그 초안과 IR 이 이 분석 결과(선택 해시)로 만든 것인지 확인하고,
    분석 결과 · 게이트 · 승인 · IR 을 한 파일로 고정한다. 단계 대응(step_map): IR 단계 번호 ↔ ③ 단계 key.
    """
    from tap.apis.gate import approve
    from tap.ir.draft_build import approved_path
    name = str(body.get("name") or "").strip()
    approver = str(body.get("approver") or "").strip()
    if not name:
        raise ValueError("시나리오 이름을 적으세요")
    if not approver:
        raise ValueError("승인자를 적으세요")
    g = pending["gate"]
    if g.status in ("차단", "실행할 것 없음"):
        raise ValueError(f"게이트 {g.status} — 등록할 수 없습니다")
    review_file = str(body.get("review_file") or "")
    review = json.loads(approved_path(root, review_file).read_text(encoding="utf-8-sig"))
    if review.get("approval_status") != "review" or (review.get("tdg_review") or {}).get("selection_hash") != g.selection_hash:
        raise ValueError("검토 전 초안이 이 분석 결과로 만든 것이 아닙니다 — 다시 분석하세요")
    ir_name = Path(str(body.get("ir_file") or "")).name
    ir_path = root / "data/out/scenario_ir_drafts" / ir_name
    if not re.fullmatch(r"SCN-[A-Za-z0-9\-]+\.json", ir_name) or not ir_path.is_file():
        raise ValueError("시나리오(IR) 파일이 없습니다 — 시나리오 생성이 끝난 뒤 등록하세요")
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    if ((ir.get("sources") or {}).get("approved") or {}).get("file") != f"{IR_INPUTS}/{review_file}":
        raise ValueError("시나리오(IR)가 이 분석 결과로 만든 것이 아닙니다 — 다시 만드세요")
    ap = approve(g, approver, bool(g.need_scenario), list(body.get("steps") or []))      # 모자라면 GateError
    pending["approval"] = ap
    cat = json.loads((root / "data/out/api_catalog.json").read_text(encoding="utf-8")) if (root / "data/out/api_catalog.json").exists() else {}
    sid, at = _stamp()
    tasks = pending["tasks"].model_dump()
    rec = {"id": "rs-" + sid, "format": "registered-v1", "name": name, "utterance": pending["request"],
           "domains": sorted({str(t["domain"]).lower() for t in tasks["tasks"]}), "registered_at": at,
           "catalog_version": cat.get("catalog_version"), "approval": ap.model_dump(), "gate": g.model_dump(),
           "tasks": tasks, "paths": pending["paths"].dump(), "selection": pending["apis"].dump(),
           "step_map": [{"step_id": f"{r['path_sequence']}-{r['step']}", "source_step": r["source_step"]} for r in review["api_selection_results"]],
           "review_file": review_file, "ir_file": str(ir_path.relative_to(root)), "ir": ir, "trace_file": pending.get("trace_file")}
    dest = root / "data/registered" / f"{rec['id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rec


def run_registered(root: Path, body: dict) -> dict:
    """실행 메뉴 — 등록 시나리오 드라이런 (2026-11-12, P4). API 를 부르지 않고 IR 로 요청을 만들어 이력에 남긴다.

    시나리오마다 실행 확인(assert_executable): 승인본 · 선택 해시 · 이번 실행에서 확인한 R2 단계. 하나라도 안 되면 아무것도 남기지 않는다.
    API 명세(카탈로그)가 등록 뒤 바뀌었으면 재승인 필요로 거부. 요청 XML = Baseline 에 IR 입력값을 덮은 것 (앞 단계 값은 {{…}}).
    """
    from tap.apis.gate import Approval, Gate, GateError, dry_run
    from tap.apis.select import ApiSelection
    from tap.ir.xml_preview import build_xml_preview
    items = body.get("items") or []
    if not items:
        raise ValueError("실행할 시나리오를 고르세요")
    cat_path = root / "data/out/api_catalog.json"
    cat_ver = json.loads(cat_path.read_text(encoding="utf-8")).get("catalog_version") if cat_path.exists() else None
    base_dir = (root / "data/out/parameters").resolve()
    rows, calls, unresolved, rollback = [], [], [], []
    for it in items:
        rec = json.loads(_registered_path(root, it.get("id")).read_text(encoding="utf-8"))
        n = int(it.get("n") or 1)
        if not 1 <= n <= 20:
            raise ValueError(f"'{rec['name']}': 반복 횟수는 1~20")
        if rec.get("catalog_version") and cat_ver and rec["catalog_version"] != cat_ver:
            raise ValueError(f"'{rec['name']}': 등록 뒤 API 명세가 바뀌었습니다 — 다시 등록(재승인)하세요")
        confirm = [str(k) for k in it.get("confirm") or []]
        try:
            dry_run(ApiSelection.model_validate(rec["selection"]), Gate.model_validate(rec["gate"]),
                    Approval.model_validate(rec["approval"]), confirm)
        except GateError as e:
            raise ValueError(f"'{rec['name']}': {e}") from e
        tier = {s["key"]: s["tier"] for s in rec["gate"]["steps"]}
        src = {m["step_id"]: m["source_step"] for m in rec.get("step_map") or []}
        rows.append({"scenario_id": rec["id"], "name": rec["name"], "count": n, "confirmed": confirm})
        steps = [s for t in (rec.get("ir") or {}).get("tasks") or [] for s in t.get("steps") or []]
        for k in range(1, n + 1):
            for s in steps:
                xml = None
                if k == 1:                              # 반복해도 요청 모양은 같다 — 첫 번만 만든다
                    f = (root / str((s.get("baseline") or {}).get("file") or "")).resolve()
                    if f.is_file() and base_dir in f.parents:
                        pv = build_xml_preview(json.loads(f.read_text(encoding="utf-8")).get("baseline_xml"), s.get("inputs") or [], s.get("bindings") or [])
                        xml = pv["applied_xml"] if pv["available"] else None
                t = tier.get(src.get(s["step_id"]))
                calls.append({"scenario": rec["name"], "scenario_id": rec["id"], "k": k, "step_id": s["step_id"], "name": s.get("edge"),
                              "api_id": (s.get("api") or {}).get("api_id"), "tier": t, "xml": xml,
                              "inputs": [{kk: x.get(kk) for kk in ("field", "source", "value", "ref")} for x in s.get("inputs") or []],
                              "bindings": [{"binding_id": b.get("binding_id"), "from_step_id": (b.get("from") or {}).get("from_step_id"),
                                            "output_name": (b.get("from") or {}).get("output_name")} for b in s.get("bindings") or []]})
                if t in ("R1", "R2"):
                    rollback.insert(0, {"name": f"{rec['name']} #{k} {s.get('edge')}", "with": "되돌리는 화살표 있음" if t == "R1" else None})
        unresolved += [f"{rec['name']} · {u.get('reason')}" for u in (rec.get("ir") or {}).get("unresolved") or [] if u.get("status") == "open"]
    return save_run(root, {"rows": rows, "calls": calls, "unresolved": unresolved, "rollback": rollback})


def save_run(root: Path, body: dict) -> dict:
    """드라이런 기록 — 실행기 연결 전이라 API 를 호출하지 않고 호출 계획만 남긴다."""
    rid, at = _stamp()
    run = {"id": "run-" + rid, "at": at, "kind": "드라이런", "rows": body.get("rows") or [], "calls": body.get("calls") or [],
           "unresolved": body.get("unresolved") or [], "rollback": body.get("rollback") or []}
    dest = root / "data/runs" / f"{run['id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run


def save_baseline(root: Path, api_id: str, body: dict) -> Path:
    """Baseline Request — 실제로 성공한 요청 값 (필드 → 값). 요청 필드에 없는 이름이면 거절."""
    from datetime import datetime
    ops = json.loads((root / "data/out/api_operations.json").read_text(encoding="utf-8"))
    op = next((o for o in ops if o["api_id"] == api_id), None)
    if op is None:
        raise ValueError(f"없는 API: {api_id}")
    if not isinstance(body, dict):
        raise ValueError("전문은 {필드: 값} 객체여야 합니다")
    extra = sorted(set(body) - {f["name"] for f in op["request_fields"]})
    if extra:
        raise ValueError(f"요청 필드에 없는 이름: {', '.join(extra)}")
    dest = root / "data/baselines" / (re.sub(r"[^A-Za-z0-9]+", "_", api_id.split(":", 2)[-1]).strip("_") + ".json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"api_id": api_id, "body": body, "by": "화면", "at": datetime.now().strftime("%m-%d %H:%M")},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def save_graph(root: Path, graph_id: str, text: str) -> dict[str, Any]:
    """화면 저장 → data/graphs/<id>.yaml. 같은 그래프 파일이 있으면 그 위에 합치고, 이전 파일은 이력으로 남긴다."""
    from tap.graph.build import graph_from_dict, merge_saved
    gid = re.sub(r"[^A-Za-z0-9_\-]", "", graph_id)
    new = yaml.safe_load(text) or {}
    if (new.get("graph") or {}).get("id") != gid:
        raise ValueError(f"그래프 id 가 맞지 않습니다: {gid} ≠ {(new.get('graph') or {}).get('id')}")
    dest = root / "data/graphs" / f"{gid}.yaml"
    old_text = dest.read_text(encoding="utf-8") if dest.exists() else None
    merged, kept = merge_saved(yaml.safe_load(old_text) if old_text else None, new)
    graph_from_dict(merged)                                 # 그래프로 안 읽히는 파일은 쓰지 않는다
    backup = None
    if old_text:
        hist = root / "data/out/graph_history"
        hist.mkdir(parents=True, exist_ok=True)
        backup = hist / f"{gid}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.yaml"
        backup.write_text(old_text, encoding="utf-8")
    head = [l for l in text.splitlines() if l.startswith("#")][:2]
    if kept:
        head.append("# 기존 파일에서 유지한 그래프 칸: " + " · ".join(kept))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(head) + "\n" + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"file": str(dest.relative_to(root)), "kept": kept,
            "backup": str(backup.relative_to(root)) if backup else None}


# ─── 분석 결과 (서버 메모리) ──────────────────────────────────────────────────────────────

class Pending:
    """선택 해시 → 서버가 계산한 분석 결과 · 게이트 · 승인. 승인 · 등록 판단은 이것으로만 한다 (화면 값은 믿지 않는다).
    서버를 다시 띄우면 사라진다. 여러 요청이 동시에 쓰므로 잠금 안에서 읽고 쓴다."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, key: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = entry

    def get(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            p = self._items.get(str(body.get("selection_hash") or ""))
        if p is None:
            raise ValueError("이 선택 결과를 서버가 모릅니다 (서버가 다시 시작됐거나 다른 결과) — 다시 분석하세요")
        return p


# ─── 시나리오 등록 · 확인용 ──────────────────────────────────────────────────────────────

def analyze(root: Path, llm, pending: Pending, body: dict[str, Any], on_stage=None) -> tuple[int, dict[str, Any]]:
    """① 요청 이해 → ② 경로 → ③ API 선택 → 권한 등급 · 승인 게이트. 결과를 pending 에 둔다. (상태 코드, 응답)"""
    from tap.cli import analyze_select
    utt = str(body.get("utterance") or "").strip()
    if not utt:
        raise ValueError("자연어 요청이 비어 있습니다")
    try:
        r = analyze_select(utt, [root / "data/graphs"], root / "data/out", root / "data/config/rules.ui.yaml",
                           llm=llm, trace_dir=root / "data/out/traces", stop_retry=body.get("stop_retry", True) is not False,
                           on_stage=on_stage)
    except Exception as e:                  # 검사 거절 · 예산 초과도 트레이스와 함께 화면에 보여 준다
        tr = getattr(e, "trace", None)
        return 400, {"error": f"{type(e).__name__}: {e}", "trace": tr.to_dict() if tr else None}
    g = r["gate"]
    pending.put(g.selection_hash, {"request": utt, "apis": r["apis"], "gate": g, "tasks": r["tasks"], "paths": r["paths"],
                                   "trace_file": str(Path(r["trace_file"]).relative_to(root))})
    return 200, {"request": utt, "tasks": r["tasks"].model_dump(), "paths": r["paths"].dump(),
                 "apis": r["apis"].dump(), "gate": g.model_dump(), "trace": r["trace"].to_dict(),
                 "notes": r["notes"], "trace_file": str(Path(r["trace_file"]).relative_to(root))}


def handoff(root: Path, p: dict[str, Any], ap, f: Path | None) -> dict[str, Any]:
    """혜정 IR 초안 생성으로 — 혜정 형식 승인본을 만들고, 혜정의 fixed_plan 으로 미리 확인한다.
    ap 가 없으면 검토 전 초안(review) — 최종 등록 화면이 승인 전에 IR 을 만든다."""
    from tap.ir.draft_build import fixed_plan
    from tap.ir.handoff import hyejung_approved, missing_materials, save_hyejung_approved
    try:
        data = hyejung_approved(p["tasks"], p["paths"], p["apis"], p["gate"], ap,
                                {**({"tdg_approval": str(f.relative_to(root))} if f else {}), "trace": p.get("trace_file")})
        plan = fixed_plan(json.loads(json.dumps(data)))
        missing = missing_materials(root, data, plan)
        if missing:                     # IR 생성 도중 자료 없음(fatal)으로 멈추기 전에 승인 때 알린다
            return {"filename": None, "error": "IR 생성에 필요한 자료가 없어 넘기지 않음: " + "; ".join(missing), "missing": missing}
        name = save_hyejung_approved(root, data)
    except (ValueError, KeyError) as e:
        return {"filename": None, "error": f"IR 초안 생성으로 넘기지 못함: {e}"}
    return {"filename": name, "file": f"{IR_INPUTS}/{name}", "steps": [
        {"step_id": f"{r['path_sequence']}-{r['step']}", "source_step": r["source_step"]} for r in data["api_selection_results"]]}


def approve(root: Path, pending: Pending, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """확인용 등록 화면의 승인 — 계획이 맞는가. 승인 기록을 data/approved/ 에 남기고 IR 생성 입력(tdg-*.json)을 만든다.
    최종 등록 화면은 register 가 승인과 등록을 함께 한다."""
    from tap.apis.gate import GateError
    from tap.apis.gate import approve as gate_approve
    p = pending.get(body)
    g = p["gate"]
    try:
        ap = gate_approve(g, str(body.get("approver") or "화면"), bool(body.get("scenario")), list(body.get("steps") or []))
    except GateError as e:
        return 400, {"error": str(e), "refused": True}
    p["approval"] = ap
    d = root / "data/approved"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{ap.selection_hash.split(':')[1][:12]}.json"
    f.write_text(json.dumps({"request": p["request"], "approval": ap.model_dump(), "gate": g.model_dump(),
                             "selection": p["apis"].dump()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 200, {"approval": ap.model_dump(), "file": str(f.relative_to(root)), "confirm_steps": g.confirm_steps,
                 "ir_handoff": handoff(root, p, ap, f)}


def review_draft(root: Path, pending: Pending, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """최종 등록 화면 — 승인 전에 IR 을 만들어 보기 위한 검토 전 초안. 차단이면 만들지 않는다."""
    p = pending.get(body)
    if p["gate"].status in ("차단", "실행할 것 없음"):
        return 400, {"error": f"게이트 {p['gate'].status} — 시나리오를 만들 수 없습니다"}
    h = handoff(root, p, None, None)
    return (200 if h.get("filename") else 400), h


def guard_human_values(root: Path, values) -> None:
    """사람이 넣는 값에 지시문이 있으면 저장하지 않는다 (요청 원문과 같은 지시문 낱말)."""
    from tap.apis.gate import detect_in_values, load_permissions
    hits = detect_in_values(values, load_permissions(root / "data/config/permissions.yaml"))
    if hits:
        raise ValueError("입력값 속 지시문 감지 — 저장하지 않음 [INJECTION_BLOCKED]: " + "; ".join(hits))


def register(root: Path, pending: Pending, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """최종 등록 화면 — 승인하고 등록. 승인이 모자라면 400 refused."""
    from tap.apis.gate import GateError
    from tap.ui.export import registered_summary
    try:
        rec = register_scenario(root, body, pending.get(body))
    except GateError as e:
        return 400, {"error": str(e), "refused": True}
    return 200, {"scenario": registered_summary(rec), "id": rec["id"]}


def registered_list(root: Path) -> list[dict[str, Any]]:
    from tap.ui.export import registered_list as load
    return load(root)                       # 화면 데이터 전체(약 3MB)를 만들지 않는다


def registered_get(root: Path, sid: str) -> dict[str, Any]:
    return json.loads(_registered_path(root, sid).read_text(encoding="utf-8"))


def registered_delete(root: Path, sid: str) -> None:
    _registered_path(root, sid).unlink()


def runs_list(root: Path) -> list[dict[str, Any]]:
    from tap.ui.export import runs_list as load
    return load(root)


# ─── IR 생성 (혜정) ─────────────────────────────────────────────────────────────────────

def check_ir_request(body: dict[str, Any]) -> dict[str, Any]:
    """생성 옵션 검사 · 예산 거부. generate 에 넘길 모드 인자를 돌려준다."""
    from tap.agent.config import generation_options
    generation_options(body.get('generation_options'), body.get('generation_mode'))
    if "budget_policy" in body or "budget" in body:
        raise ValueError("예산은 서버에서 자동 산정합니다")
    return {key: body[key] for key in ('generation_mode', 'generation_options') if key in body}


def generate_ir(root: Path, body: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    from tap.ir.draft_build import generate
    return generate(root, body.get("approved_filename"), body.get("generation_config"), **mode)


def generate_ir_stream(root: Path, body: dict[str, Any], mode: dict[str, Any], emit: Emit) -> None:
    """IR 생성 진행을 한 줄씩. 진행 이벤트는 인증값을 가린 사본, 마지막 결과는 원본 그대로."""
    from tap.agent.progress import snapshot
    from tap.ir.draft_build import generate
    try:
        result = generate(root, body.get('approved_filename'), body.get('generation_config'),
                          on_event=lambda event: emit(snapshot(event)), **mode)
        emit({'event': 'generation_complete', 'result': result})
    except Exception as error:
        emit({'event': 'generation_error', 'error': str(error), 'log_file': getattr(error, 'log_file', None),
              'log_url': getattr(error, 'log_url', None)})


def approved_selections(root: Path) -> dict[str, Any]:
    """확인용 IR 영역 — 승인본 목록 (검토 전 초안은 빼고) · 생성 기본값."""
    from tap.agent.config import DEFAULTS, DEFAULT_GENERATION_MODE, DEFAULT_OPTIONS, GENERATION_MODES
    rows = []
    for file in sorted((root / IR_INPUTS).glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8-sig"))
            if data.get("approval_status") == "review":
                continue
            rows.append({"filename": file.name, "original_question": data.get("original_question"), "approval_status": data.get("approval_status")})
        except (ValueError, OSError):
            continue
    return {"files": rows, "defaults": DEFAULTS, "default_generation_options": dict(DEFAULT_OPTIONS),
            "default_generation_mode": DEFAULT_GENERATION_MODE, "generation_modes": GENERATION_MODES}


def ir_budget(root: Path, filename: str) -> dict[str, Any]:
    from tap.agent.budget import calculate
    from tap.ir.draft_build import approved_path, fixed_plan
    approved = json.loads(approved_path(root, filename).read_text(encoding='utf-8-sig'))
    return {'budget': calculate(len(fixed_plan(approved)))}


def ir_log_file(root: Path, name: str) -> Path | None:
    """생성 로그 JSONL — 이름은 IRRUN-….jsonl 만, 폴더 밖은 거부. 없으면 None."""
    folder = (root / 'data/out/scenario_ir_logs').resolve()
    file = (folder / name).resolve()
    if not re.fullmatch(r'IRRUN-[A-Za-z0-9-]+\.jsonl', name) or file.parent != folder or not file.is_file():
        return None
    return file


# ─── 관리자 ───────────────────────────────────────────────────────────────────────────

def build_again(root: Path) -> dict[str, Any]:
    before = json.loads((root / "data/out/api_catalog.json").read_text(encoding="utf-8"))
    r = rebuild(root)
    return {"build": r, "changed": r["catalog_version"] != before.get("catalog_version"), "data": ui_data(root)}


def refresh_preprocessing(root: Path) -> dict[str, Any]:
    """노트북은 실행하지 않고 이미 생성된 JSON 을 다시 읽어 정적 화면 데이터에도 반영한다."""
    write_ui_data(root, root / "web/tap-data.js")
    return {"data": ui_data(root)}


def save_preprocessing(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    guard_human_values(root, body.get("values"))
    dest = save_preprocessing_baseline(root, body["selected_api_id"], body["values"])
    return {"file": str(dest.relative_to(root)), "data": ui_data(root)}


# ─── 화면 데이터 나누기 · 그래프 매칭 (React 전환 R0, docs/react.md 6절) ─────────────────────

DATA_PARTS = {                              # 화면이 필요한 만큼만 — 예전 /tap-data.js 한 덩어리를 나눈 것
    "environment": ("generated_at", "build", "connections", "tools", "overrides_file"),
    "catalog": ("catalog",), "metadata": ("metadata",), "operations": ("ops",), "review": ("review",),
    "graphs": ("graphs", "drafts"), "codes": ("codes",), "rules": ("rules",), "baselines": ("baselines",),
    "preprocessing": ("preprocessing",),
}


def data_part(root: Path, part: str) -> dict[str, Any]:
    """화면 데이터 한 덩어리 — 그 칸만 만든다 (전처리 산출물 3MB 를 매번 읽지 않게)."""
    from tap.ui.export import ui_part
    return ui_part(root, DATA_PARTS[part])


def preprocessing_status(root: Path) -> dict[str, Any]:
    """머리의 전처리 상태 줄 — 개수 · 경고 · 읽은 시각만 (산출물 본문은 /api/admin/preprocessing)."""
    p = data_part(root, "preprocessing")["preprocessing"]
    return {"counts": p.get("counts"), "warnings": p.get("warnings") or [], "loaded_at": p.get("loaded_at")}


def _match_inputs(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    out = root / "data/out"
    return (json.loads((out / "api_metadata.json").read_text(encoding="utf-8")),
            json.loads((out / "api_operations.json").read_text(encoding="utf-8")))


def graph_match(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """상태 그래프 편집기의 API 후보 미리보기 — 화살표(쓰기) · 상태(조회)마다 후보와 찾음 / 확인 필요 / 없음.
    예전에는 graph-editor.js 가 tap.graph.match 를 JS 로 복사해 계산했다 — 이제 서버의 한 벌만 쓴다."""
    from tap.graph.match import match_edge, match_lookup, status_of
    metadata, operations = _match_inputs(root)
    doms = body.get("domains") or ["pd", "od", "ds"]
    field, top = body.get("state_field"), int(body.get("top") or 3)          # 편집기와 같게 상위 3개
    dump = lambda cs: {"status": status_of(cs), "candidates": [c.model_dump() for c in cs]}
    return {
        "edges": [dump(match_edge(e.get("name"), str(e.get("from_name") or ""), str(e.get("to_name") or ""), metadata, doms,
                                  top=top, operations=operations, state_field=field, to_code=e.get("to_code")))
                  for e in body.get("edges") or []],
        "lookups": [dump(match_lookup(str(x.get("state_name") or ""), str(x.get("state_code") or ""), metadata, operations,
                                      field, doms, top=top)) for x in body.get("lookups") or []],
    }


def graph_review(root: Path, domains: list[str] | None = None) -> list[dict[str, Any]]:
    """관리자 › 전사 검수 목록의 '상태 그래프' 부분 — API 를 못 찾을 것 같은 화살표 · 애매한 조회 (예전 GraphEditor.reviewItems)."""
    from tap.graph.match import match_edge, match_lookup, status_of
    metadata, operations = _match_inputs(root)
    doms = domains or ["pd", "od", "ds"]
    from tap.ui.export import ui_part
    d = ui_part(root, ("graphs", "drafts", "codes"))
    graphs = d["graphs"] + [x for x in d["drafts"] if x and x.get("graph") and not any(g["graph"]["id"] == x["graph"]["id"] for g in d["graphs"])]
    out = []
    for g in graphs:
        codes = next((c for c in d["codes"] if c["id"] == g["code_group"]["id"]), g["code_group"])
        nm = lambda c: codes["codes"].get(str(c), str(c))
        field = g["graph"].get("state_field")
        for t in [t for t in g.get("transitions") or [] if t.get("name")]:
            cs = match_edge(t["name"], nm(t["from"]), nm(t["to"]), metadata, doms, top=5, operations=operations,
                            state_field=field, to_code=str(t["to"]))
            if status_of(cs) != "찾음":
                out.append({"graph": g["graph"]["name"], "gid": g["graph"]["id"], "kind": "화살표", "status": status_of(cs),
                            "item": f"{t['name']} ({nm(t['from'])} → {nm(t['to'])})",
                            "why": " · ".join(cs[0].reasons) if cs else "후보 없음 — 명세 summary · 별칭 · 구분값 어디에도 비슷한 이름이 없음"})
        states = list(dict.fromkeys([str(s) for t in g.get("transitions") or [] for s in (t["from"], t["to"])] + list((g.get("layout") or {}).keys())))
        for c in states:
            cs = match_lookup(nm(c), c, metadata, operations, field, doms, top=5)
            if status_of(cs) == "확인 필요":
                out.append({"graph": g["graph"]["name"], "gid": g["graph"]["id"], "kind": "조회", "item": f"{c} {nm(c)}",
                            "status": "확인 필요", "why": " · ".join(cs[0].reasons)})
    return out
