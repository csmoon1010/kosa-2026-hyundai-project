"""계획 에이전트의 도구 — 모두 읽기 전용(R0). 우리 메타데이터 · 그래프만 읽고 개발 서버는 부르지 않는다.

도구는 기존 코드를 감싼다: 경로 계산(paths._routes · build_paths), 후보 찾기 · 확정 검사 · 규칙 추천(select.prepare_steps · check).
LLM 은 도구로 찾아보고 고르기만 한다. 경로(화살표)는 코드가 계산하고, 제출한 계획은 submit_plan 이 코드로 검사한다.
도구 결과에는 코드값을 주지 않는다 — 상태는 이름, API 는 operation id 로 말한다.

도구 결과는 하나에 RESULT_CHARS 자까지만 담는다 (컨텍스트 압축).
"""
from __future__ import annotations

import json
from typing import Any

from tap.apis.select import (SCOPE, TOP, ApiSelection, Selected, Unresolved, _field_hits, _show_fields, check,
                             finish_selection, prepare_steps)
from tap.goal.extract import GoalError, TaskPlan
from tap.graph.match import Candidate, sim
from tap.graph.model import NEW, StateGraph
from tap.graph.paths import PathPlan, TaskPath, build_paths, mentions, to_choices

RESULT_CHARS = 1500


class Session:
    """에이전트 한 번 (요청 하나) 동안의 상태 — 도구가 계산한 경로 · 본 API · 호출 기록."""

    def __init__(self, tp: TaskPlan, graphs: list[StateGraph], metadata: list[dict[str, Any]],
                 operations: list[dict[str, Any]], catalog: dict[str, Any] | None = None):
        self.tp, self.graphs, self.operations, self.catalog = tp, graphs, operations, catalog
        if catalog is not None:                 # 카탈로그 = 후보로 쓸 수 있는 API 목록 (사용 중인 것만)
            allowed = {a["api_id"] for a in catalog.get("apis") or [] if a.get("tool_enabled", True)}
            metadata = [m for m in metadata if m["api_id"] in allowed]
        self.metadata = metadata
        self.meta = {m["api_id"]: m for m in metadata}
        self.by_op = {m["operation_id"]: m["api_id"] for m in metadata if m.get("operation_id")}
        self.ops = {o["api_id"]: o for o in operations}
        self.req = {o["api_id"]: {f["name"] for f in o["request_fields"]} for o in operations}
        self.by_id = {g.graph_id: g for g in graphs}
        self.choices: dict[int, dict[str, Any]] = {}      # find_route 로 정한 업무별 그래프 · 상태 (LLM 이 보낸 이름 그대로)
        self.paths: dict[int, TaskPath] = {}
        self.seen: set[str] = set()                        # 도구 결과에 나온 API — 계획에는 이 안에서만 고른다
        self.log: list[dict[str, Any]] = []                # 도구 호출 기록 (궤적)
        self.rejections: list[list[str]] = []
        self.result: dict[str, Any] | None = None          # 받아들인 계획 {paths, apis, notes}

    # ── 공통 ──
    def api_id(self, name: str | None) -> str | None:
        if not name:
            return None
        if name in self.meta:
            return name
        return self.by_op.get(name) or self.by_op.get(name.rsplit("/", 1)[-1].removesuffix(".do"))

    def op(self, api_id: str) -> str:
        return self.meta.get(api_id, {}).get("operation_id") or api_id.rsplit("/", 1)[-1]

    def _graph(self, gid: str | None) -> StateGraph:
        g = self.by_id.get(gid or "")
        if g is None:
            raise ToolError(f"알 수 없는 그래프 {gid} — list_graphs 로 확인")
        return g

    def _task(self, seq: int):
        t = next((t for t in self.tp.tasks if t.sequence == seq), None)
        if t is None:
            raise ToolError(f"업무 {seq} 가 없음 — 업무 sequence 는 {[t.sequence for t in self.tp.tasks]}")
        return t

    # ── 그래프 ──
    def list_graphs(self, domain: str | None = None) -> dict[str, Any]:
        gs = [g for g in self.graphs if not domain or g.domain.lower() == domain.lower()]
        return {"graphs": [{"graph_id": g.graph_id, "name": g.name, "domain": g.domain.upper(), "entity": g.entity,
                            "states": len(g.nodes)} for g in gs]}

    def get_graph(self, graph_id: str) -> dict[str, Any]:
        g = self._graph(graph_id)
        entry = set(g.entry_states)
        return {"graph_id": g.graph_id, "name": g.name, "domain": g.domain.upper(), "entity": g.entity,
                "states": [{"name": n.name, **({"synonyms": n.synonyms} if n.synonyms else {}),
                            **({"entry": True} if n.code in entry else {}),
                            **({"ready": True} if n.code == g.ready_state else {}),
                            "findable": n.lookup is not None} for n in g.nodes],
                "arrows": [{"name": e.name, "from": g.name_of(e.from_code), "to": g.name_of(e.to_code)}
                           for e in g.edges if e.kind == "api"],
                "note": f"'{NEW}'에서 나가는 화살표 = 새로 만들기. findable = 조회로 바로 찾을 수 있는 상태"}

    def find_state(self, word: str, graph_id: str | None = None) -> dict[str, Any]:
        gs = [self._graph(graph_id)] if graph_id else self.graphs
        hits = []
        for g in gs:
            states, to, frm = mentions(word, g)
            for c in states:
                hits.append({"graph_id": g.graph_id, "state": g.name_of(c), "by": "상태 이름 · 다른 표현"})
            for e in g.edges:
                if e.kind == "api" and e.to_code in to and e.from_code in frm and sim(word, e.name) >= 0.6:
                    hits.append({"graph_id": g.graph_id, "arrow": e.name, "from": g.name_of(e.from_code),
                                 "to": g.name_of(e.to_code), "by": "동작 이름"})
            if not states and not to:
                for n in g.nodes:
                    s = max(sim(word, n.name), *(sim(word, w) for w in n.synonyms or [""]))
                    if s >= 0.6:
                        hits.append({"graph_id": g.graph_id, "state": n.name, "by": f"비슷함 {s:.2f} — 요청의 말과 같은지 확인"})
        return {"word": word, "matches": hits or "없음 — 그래프에 이 상태 · 동작이 없을 수 있음"}

    # ── 경로 ──
    def _plan_with(self, override: dict[int, dict[str, Any]]) -> tuple[PathPlan, list[str], list[str]]:
        """업무마다 그래프 · 상태 (없으면 그래프 없음) → 검사 → 경로. 검사에서 틀리면 ToolError."""
        raw = []
        for t in self.tp.tasks:
            c = override.get(t.sequence) or self.choices.get(t.sequence) or {"graph_id": None}
            raw.append({"sequence": t.sequence, "graph_id": c.get("graph_id"), "from_state": c.get("from_state"),
                        "to_state": c.get("to_state"), "must_pass": c.get("must_pass") or [],
                        "state_phrases": c.get("state_phrases") or [], "reason": c.get("reason") or ""})
        try:
            choices, unresolved, notes = to_choices({"choices": raw, "unresolved": []}, self.tp, self.graphs)
        except GoalError as e:
            raise ToolError(str(e)) from e
        pp = build_paths(self.tp, choices, self.graphs)
        return pp, unresolved, notes

    def _routes_of(self, p: TaskPath) -> list[TaskPath]:
        alts = [p.model_copy(update={"from_state": a.from_state, "start_by": a.start_by, "steps": a.steps, "alternatives": []})
                for a in p.alternatives]
        return [p] + alts

    def _step_list(self, p: TaskPath) -> list[dict[str, Any]]:
        if p.status == "경로 없음":
            return []
        ctx = prepare_steps(self.tp, PathPlan(original_question=self.tp.original_question, paths=[p], unresolved=[]),
                            self.graphs, self.metadata, self.operations)
        return [{"step": x["st"]["step"], "kind": x["st"]["kind"], "edge": x["st"]["edge"],
                 **({"from": x["st"]["from"]} if x["st"]["from"] else {}), **({"to": x["st"]["to"]} if x["st"]["to"] else {})}
                for x in ctx["steps"]]

    def find_route(self, sequence: int, graph_id: str | None, from_state: str | None = None, to_state: str | None = None,
                   must_pass: list[str] | None = None, state_phrases: list[str] | None = None) -> dict[str, Any]:
        self._task(sequence)
        c = {"graph_id": graph_id, "from_state": from_state, "to_state": to_state, "must_pass": must_pass or [],
             "state_phrases": state_phrases or []}
        pp, unresolved, notes = self._plan_with({sequence: c})
        p = next(x for x in pp.paths if x.sequence == sequence)
        self.choices[sequence], self.paths[sequence] = c, p
        mine = [u for u in unresolved + pp.unresolved if u.startswith(f"{sequence}번 업무")]
        out: dict[str, Any] = {"sequence": sequence, "status": p.status, "graph_id": p.graph_id}
        if p.status == "ok":
            out.update(to_state=p.to_state, to_state_reason=p.to_state_reason)
            out["routes"] = [{"route": i, "from_state": r.from_state, "start_by": r.start_by,
                              **({"why": p.alternatives[i - 1].why} if i else {}), "steps": self._step_list(r)}
                             for i, r in enumerate(self._routes_of(p))]
        elif p.status == "그래프 없음":
            out["routes"] = [{"route": 0, "steps": self._step_list(p)}]
        else:                                   # 경로 없음 — 고를 단계가 없다
            out["routes"] = []
            out["next"] = "경로가 없어 고를 단계가 없음 — 그래프 · 상태를 다시 볼 게 아니면 이 업무는 apis 없이 submit_plan (결과는 보류)"
        notes = [n for n in notes if n.startswith(f"{sequence}번")] + p.notes
        if notes:
            out["notes"] = notes
        if mine:
            out["unresolved"] = mine
        return out

    def _path(self, sequence: int, route: int) -> TaskPath:
        p = self.paths.get(sequence)
        if p is None:
            raise ToolError(f"업무 {sequence} 의 경로가 없음 — find_route 를 먼저 부르기")
        rs = self._routes_of(p)
        if route < 0 or route >= len(rs):
            raise ToolError(f"업무 {sequence} 에 route {route} 가 없음 (0~{len(rs) - 1})")
        return rs[route]

    def _step(self, sequence: int, step: int, route: int) -> dict[str, Any]:
        p = self._path(sequence, route)
        ctx = prepare_steps(self.tp, PathPlan(original_question=self.tp.original_question, paths=[p], unresolved=[]),
                            self.graphs, self.metadata, self.operations)
        x = next((x for x in ctx["steps"] if x["st"]["step"] == step), None)
        if x is None:
            have = [y["st"]["step"] for y in ctx["steps"]]
            raise ToolError(f"업무 {sequence} route {route} 에 단계 {step} 가 없음 — " + (f"있는 단계 {have}" if have else
                            f"경로가 {p.status}라 고를 단계가 없음, 이 업무는 apis 없이 submit_plan"))
        return x

    # ── API ──
    def step_candidates(self, sequence: int, step: int, route: int = 0) -> dict[str, Any]:
        x = self._step(sequence, step, route)
        st, rule = x["st"], x["rule"]
        cands = []
        for c, k, w in sorted(x["judged"], key=lambda y: -y[0].score):
            self.seen.add(c.api_id)
            cands.append({"api": self.op(c.api_id), "name": c.api_name, "selector": c.selector, "score": round(c.score, 2),
                          "check": k, **({"check_reason": w} if w else {}), "why": "; ".join(c.reasons)[:120]})
        rec = None
        if rule and rule["selected"]:
            rec = {"api": self.op(rule["selected"].api_id), "selector": rule["selected"].selector, "status": rule["status"],
                   "reason": rule["reason"][:200]}
        return {"sequence": sequence, "step": step, "route": route, "kind": st["kind"], "edge": st["edge"],
                "terms": st.get("terms") or [], "candidates": cands or "후보 없음",
                "rule_recommendation": rec or ("없음 — " + rule["reason"] if rule else "없음 — 1 · 2순위가 비슷함, 직접 판단")}

    def search_apis(self, query: str, kind: str, domain: str | None = None) -> dict[str, Any]:
        want = {"조회": "read", "쓰기": "write"}.get(kind)
        if want is None:
            raise ToolError("kind 는 조회 · 쓰기 중 하나")
        out = []
        for m in self.metadata:
            if m["kind"] != want or not m.get("tool_enabled", True) or m["domain"] not in SCOPE:
                continue
            if domain and m["domain"] != domain.lower():
                continue
            names = [m["api_name"], m.get("operation_id") or "", *(m.get("aliases") or [])]
            names += [v.get("name") or "" for s in m.get("selectors") or [] for v in s["values"]]
            names += [a for s in m.get("selectors") or [] for v in s["values"] for a in v.get("aliases") or []]
            s_name = max(sim(query, n) for n in names if n) if any(names) else 0.0
            fields = self.ops.get(m["api_id"], {}).get("request_fields") or []
            hit = next((f for f in fields if sim(query, f.get("label")) >= 0.8 or sim(query, f["name"]) >= 0.8), None)
            score = max(s_name, 0.7 if hit else 0.0)
            if score >= 0.3:
                out.append((score, m, hit))
        out.sort(key=lambda x: (-x[0], x[1]["api_id"]))
        res = []
        for score, m, hit in out[:TOP]:
            self.seen.add(m["api_id"])
            res.append({"api": m.get("operation_id"), "name": m["api_name"], "action": m.get("action"), "score": round(score, 2),
                        **({"field": f"{hit['name']}({hit.get('label') or ''})"} if hit else {}),
                        "selectors": {s["field"]: [v["value"] for v in s["values"]] for s in m.get("selectors") or []}})
        return {"query": query, "kind": kind, "apis": res or "없음"}

    def get_api(self, api: str, field_query: list[str] | None = None) -> dict[str, Any]:
        aid = self.api_id(api)
        if aid is None:
            raise ToolError(f"모르는 API {api} — operation id 로 (예: multiOshpProcess)")
        self.seen.add(aid)
        m, o = self.meta[aid], self.ops.get(aid, {})
        terms = field_query or []
        return {"api": m.get("operation_id"), "name": m["api_name"], "description": m.get("description"),
                "kind": "조회" if m["kind"] == "read" else "쓰기", "action": m.get("action"), "domain": m["domain"],
                "irreversible": m.get("irreversible"), "aliases": m.get("aliases") or [],
                "selectors": [{"field": s["field"], "label": s.get("label"), "complete": s.get("complete"),
                               "values": [{"value": v["value"], "name": v.get("name"), **({"aliases": v["aliases"]} if v.get("aliases") else {})}
                                          for v in s["values"]]} for s in m.get("selectors") or []],
                "request_fields": _show_fields(o.get("request_fields") or [], terms),
                "response_fields": _show_fields(o.get("response_fields") or [], terms)}

    def check_api(self, sequence: int, step: int, api: str, selector: dict[str, str] | None = None, route: int = 0) -> dict[str, Any]:
        x = self._step(sequence, step, route)
        aid = self.api_id(api)
        if aid is None:
            raise ToolError(f"모르는 API {api}")
        self.seen.add(aid)
        g = x["g"]
        k, w = check(Candidate(api_id=aid, api_name=self.meta[aid]["api_name"], score=0.0, selector=selector or {}),
                     x["st"]["kind"], self.meta, self.req, g.state_field if g else None)
        return {"api": self.op(aid), "selector": selector or {}, "check": k, **({"reason": w} if w else {})}

    # ── 제출 ──
    def submit_plan(self, paths: list[dict[str, Any]], apis: list[dict[str, Any]], unresolved: list[str] | None = None) -> dict[str, Any]:
        """계획 검사 — 지금 있는 검사를 모두 다시 한다. 틀리면 이유 목록을 돌려주고 받아들이지 않는다."""
        errs: list[str] = []
        by_seq = {}
        for p in paths:
            if p["sequence"] in by_seq:
                errs.append(f"업무 {p['sequence']} 가 두 번 있음")
            by_seq[p["sequence"]] = p
        want = {t.sequence for t in self.tp.tasks}
        if set(by_seq) != want:
            errs.append(f"업무마다 하나씩: 업무 {sorted(want)}, 제출 {sorted(by_seq)}")
            return self._reject(errs)
        try:
            pp, llm_unresolved, notes = self._plan_with({s: {**p} for s, p in by_seq.items()})
        except ToolError as e:
            return self._reject([str(e)])
        chosen = []
        for p in pp.paths:                      # 대안 경로를 고른 업무는 그 경로로
            r = by_seq[p.sequence].get("route") or 0
            if r and p.status != "ok":
                errs.append(f"업무 {p.sequence}: 경로가 {p.status}라 route {r} 를 쓸 수 없음")
                chosen.append(p)
                continue
            if r:
                if r > len(p.alternatives):
                    errs.append(f"업무 {p.sequence}: route {r} 가 없음 (대안 {len(p.alternatives)}개)")
                    chosen.append(p)
                    continue
                a = p.alternatives[r - 1]
                rest = [x for i, x in enumerate(p.alternatives) if i != r - 1]
                p = p.model_copy(update={"from_state": a.from_state, "start_by": a.start_by, "steps": a.steps, "alternatives": rest,
                                         "notes": p.notes + [f"대안 경로를 씀 ({a.from_state}에서 {a.start_by}, {a.why})"]})
            chosen.append(p)
        pp = pp.model_copy(update={"paths": chosen})
        pp.unresolved = list(dict.fromkeys(list(self.tp.unresolved) + llm_unresolved + pp.unresolved))
        ctx = prepare_steps(self.tp, pp, self.graphs, self.metadata, self.operations, self.catalog)
        picks: dict[tuple[int, int], dict[str, Any]] = {}
        for a in apis:
            k = (a["sequence"], a["step"])
            if k in picks:
                errs.append(f"단계 {k[0]}-{k[1]} 가 두 번 있음")
            picks[k] = a
        keys = {(x["path"].sequence, x["st"]["step"]) for x in ctx["steps"]}
        for k in sorted(set(picks) - keys):
            errs.append(f"단계 {k[0]}-{k[1]} 는 고른 경로에 없음 — 경로의 단계는 {sorted(f'{a}-{b}' for a, b in keys)}")
        rows: list[dict[str, Any]] = []
        unres: list[Unresolved] = list(ctx["unresolved"])
        for x in ctx["steps"]:
            st, row, rule = x["st"], x["row"], x["rule"]
            key = (x["path"].sequence, st["step"])
            a = picks.get(key)
            if a is None:
                errs.append(f"단계 {key[0]}-{key[1]} '{st['edge']}' 의 API 를 정하지 않음 — 맞는 API 가 없으면 api 를 null 로")
                continue
            reason = (a.get("reason") or "").strip()
            if not a.get("api"):
                why = "에이전트가 맞는 API 가 없다고 함" + (f" — {reason}" if reason else "")
                rows.append({**row, "selected": None, "selection_status": "보류", "selected_by": "LLM", "selection_reason": why})
                unres.append(Unresolved(path_sequence=key[0], step=key[1], reason=f"'{st['edge']}': {why}"))
                continue
            aid = self.api_id(a["api"])
            if aid is None:
                errs.append(f"단계 {key[0]}-{key[1]}: 모르는 API {a['api']}")
                continue
            if aid not in self.seen:
                errs.append(f"단계 {key[0]}-{key[1]}: {self.op(aid)} 는 도구 결과에 나온 적 없는 API — step_candidates · search_apis 로 찾은 것만")
                continue
            sel = {s["field"]: s["value"] for s in a.get("selector") or []} if isinstance(a.get("selector"), list) else dict(a.get("selector") or {})
            k, w = check(Candidate(api_id=aid, api_name=self.meta[aid]["api_name"], score=0.0, selector=sel), st["kind"],
                         ctx["meta"], ctx["req"], x["g"].state_field if x["g"] else None)
            if k == "탈락":
                errs.append(f"단계 {key[0]}-{key[1]}: {self.op(aid)} {sel} 확정 검사 탈락 — {w}")
                continue
            miss = [t for t in st.get("terms") or [] if t not in _field_hits([t], aid, self.ops)] if st["kind"] == "수정" else []
            if miss:                            # 값을 바꾸는 업무 — 바꿀 값을 담을 요청 필드가 없으면 그 API 로는 못 한다
                errs.append(f"단계 {key[0]}-{key[1]}: {self.op(aid)} 의 요청 필드에 설정값 {miss} 를 담을 필드가 없음 "
                            "— get_api 로 확인하고, 맞는 API 가 없으면 api 를 null 로(보류)")
                continue
            rs = rule["selected"] if rule else None
            if rs and rs.api_id == aid and rs.selector == sel:     # 규칙 추천을 따름 — 결과는 워크플로와 같다
                rows.append({**row, "selected": rs, "selection_status": rule["status"], "selected_by": "규칙",
                             "selection_reason": rule["reason"]})
                continue
            concerns = list(a.get("concerns") or []) + ([w] if w else [])
            if st["loose"]:
                concerns.append("그래프 없는 업무라 명세만으로 고름")
            if not any(c.api_id == aid and c.selector == sel for c, _, _ in x["passed"]):
                concerns.append("매칭기 후보(점수 0.45 이상) 밖에서 고름")
            if rs:
                concerns.append(f"규칙 추천({self.op(rs.api_id)} {rs.selector})과 다르게 고름")
            rows.append({**row, "selected": Selected(api_id=aid, selector=sel), "selected_by": "LLM",
                         "selection_status": "가선택" if concerns else "선택",
                         "selection_reason": reason + (f" (확인: {' · '.join(concerns)})" if concerns else "")})
            for c in concerns:
                unres.append(Unresolved(path_sequence=key[0], step=key[1], reason=c))
        if errs:
            return self._reject(errs)
        unres += [Unresolved(path_sequence=None, step=None, reason=f"에이전트: {u}") for u in unresolved or []]
        sel_out: ApiSelection = finish_selection(self.tp, pp, rows, unres, ctx, self.operations)
        self.result = {"paths": pp, "apis": sel_out, "notes": notes}
        return {"accepted": True, "status": sel_out.status,
                "steps": [f"{r.path_sequence}-{r.step} {r.selection_status}" for r in sel_out.api_selection_results]}

    def _reject(self, errs: list[str]) -> dict[str, Any]:
        self.rejections.append(errs)
        return {"accepted": False, "errors": errs, "hint": "고쳐서 submit_plan 을 다시 부르기"}


class ToolError(ValueError):
    """도구 입력이 틀림 — 이유를 도구 결과로 돌려준다 (LLM 이 고쳐 다시 부른다)."""


def clip(obj: Any) -> str:
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= RESULT_CHARS else s[:RESULT_CHARS - 20] + " …(잘림)"


# ─── 도구 정의 (OpenAI function calling, strict) ─────────────────────────────────────────

def _fn(name: str, desc: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": desc, "strict": True,
                                             "parameters": {"type": "object", "properties": props,
                                                            "required": list(props), "additionalProperties": False}}}


def _nullable(t: dict[str, Any]) -> dict[str, Any]:
    if "enum" in t:
        return {**t, "type": [t["type"], "null"], "enum": [*t["enum"], None]}
    return {**t, "type": [t["type"], "null"]}


def tool_specs(graphs: list[StateGraph]) -> list[dict[str, Any]]:
    gids = [g.graph_id for g in graphs]
    states = list(dict.fromkeys(n.name for g in graphs for n in g.nodes))
    G = {"type": "string", "enum": gids, "description": "그래프 ID"} if gids else {"type": "string"}
    S = {"type": "string", "enum": states} if states else {"type": "string"}
    seq = {"type": "integer", "description": "업무 sequence"}
    step = {"type": "integer", "description": "단계 번호 (find_route 결과의 step, 0 = 출발 데이터 조회)"}
    route = {"type": "integer", "description": "find_route 결과의 route (0 = 기본 경로)"}
    api = {"type": "string", "description": "API operation id (예: multiOshpProcess)"}
    selector = {"type": "array", "description": "구분값 — 없으면 []",
                "items": {"type": "object", "properties": {"field": {"type": "string"}, "value": {"type": "string"}},
                          "required": ["field", "value"], "additionalProperties": False}}
    return [
        _fn("list_graphs", "상태 그래프 목록 (그래프 하나 = 한 대상의 상태 코드 그룹)",
            {"domain": _nullable({"type": "string", "description": "도메인 (PD · OD · DS), 전체면 null"})}),
        _fn("get_graph", "그래프의 상태(이름 · 다른 표현 · 조회로 찾을 수 있는지)와 화살표(동작 이름 · 출발 → 도착)", {"graph_id": G}),
        _fn("find_state", "요청의 말과 맞는 상태 · 동작 찾기 (상태 이름 · 다른 표현 · 동작 이름)",
            {"word": {"type": "string", "description": "요청에 나온 말 (예: 배송완료, 발송된)"}, "graph_id": _nullable(G)}),
        _fn("find_route", "업무 하나의 경로 계산 — 그래프 · 출발 · 목표 · 거칠 상태를 주면 코드가 화살표를 찾는다. 상태를 다루지 않는 업무는 graph_id null",
            {"sequence": seq, "graph_id": _nullable(G),
             "from_state": _nullable({**S, "description": "기존 업무에서 요청이 말한 '이미 그 상태인 데이터'의 상태. 없거나 신규면 null"}),
             "to_state": _nullable({**S, "description": "업무가 끝났을 때의 상태. 요청이 말하지 않으면 null"}),
             "must_pass": {"type": "array", "items": S, "description": "출발 상태를 말하지 않았는데 거쳐야 할 상태. 그 밖에는 []"},
             "state_phrases": {"type": "array", "items": {"type": "string"}, "description": "상태를 정한 근거 구절 — 요청 원문에서 그대로 복사"}}),
        _fn("step_candidates", "경로 단계의 API 후보 (매칭기 점수 · 확정 검사 · 규칙 추천)", {"sequence": seq, "step": step, "route": route}),
        _fn("search_apis", "API 를 이름 · 별칭 · 구분값 이름 · 요청 필드로 찾기 (후보가 맞지 않을 때)",
            {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["조회", "쓰기"]},
             "domain": _nullable({"type": "string", "description": "pd · od · ds, 전체면 null"})}),
        _fn("get_api", "API 자세히 — 설명 · 구분값 목록 · 요청/응답 필드 (field_query 와 맞는 필드를 먼저)",
            {"api": api, "field_query": {"type": "array", "items": {"type": "string"}, "description": "찾을 필드 말 (예: 브랜드코드). 없으면 []"}}),
        _fn("check_api", "그 단계에 이 API · 구분값을 써도 되는지 확정 검사 (통과 · 주의 · 탈락)",
            {"sequence": seq, "step": step, "route": route, "api": api, "selector": selector}),
        _fn("submit_plan", "계획 제출 — 업무마다 경로, 단계마다 API. 코드가 검사해서 받아들이거나 이유와 함께 거절한다",
            {"paths": {"type": "array", "description": "업무마다 하나 (find_route 에 준 값과 같게)", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["sequence", "graph_id", "from_state", "to_state", "must_pass", "state_phrases", "route", "reason"],
                "properties": {"sequence": seq, "graph_id": _nullable(G), "from_state": _nullable(S), "to_state": _nullable(S),
                               "must_pass": {"type": "array", "items": S}, "state_phrases": {"type": "array", "items": {"type": "string"}},
                               "route": route, "reason": {"type": "string", "description": "그래프 · 상태 · 경로를 고른 이유 한 문장"}}}},
             "apis": {"type": "array", "description": "고른 경로의 단계마다 하나", "items": {
                 "type": "object", "additionalProperties": False,
                 "required": ["sequence", "step", "api", "selector", "reason", "concerns"],
                 "properties": {"sequence": seq, "step": step, "api": _nullable({**api, "description": "맞는 API 가 없으면 null (보류)"}),
                                "selector": selector, "reason": {"type": "string", "description": "명세의 어떤 내용 때문에 골랐는지 한 문장"},
                                "concerns": {"type": "array", "items": {"type": "string"}, "description": "고르기는 했지만 사람이 확인해야 할 점"}}}},
             "unresolved": {"type": "array", "items": {"type": "string"}, "description": "정하지 못한 것 · 애매한 것"}}),
    ]


TOOL_TIER = {s: "R0" for s in ("list_graphs", "get_graph", "find_state", "find_route", "step_candidates", "search_apis",
                                "get_api", "check_api", "submit_plan")}   # 모두 읽기 — 쓰기 도구는 에이전트에 없다


def call_tool(s: Session, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_TIER:
        raise ToolError(f"없는 도구 {name}")
    if name == "check_api":
        args = {**args, "selector": {x["field"]: x["value"] for x in args.get("selector") or []}}
    return getattr(s, name)(**args)
