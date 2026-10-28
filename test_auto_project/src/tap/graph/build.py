"""State Graph Builder / Validator.

지금은 사람이 확인한 업무 지식(data/knowledge/*.yaml)으로 그래프를 만든다.
문서 · 이력에서 자동 추출한 간선은 나중에 같은 모델로 합류한다 (source 로 구분).
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import yaml

from tap.graph.model import Edge, Lookup, StateGraph, StateNode


def load_knowledge(path: str | Path) -> StateGraph:
    return graph_from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def load_graphs(paths: list[str | Path]) -> tuple[list[StateGraph], list[str]]:
    """시나리오 생성에 쓸 그래프 전부 — 사람이 확인한 그래프(data/knowledge) + 화면 저장본(data/out/graphs).

    같은 그래프 id 는 뒤에 오는 것(화면 저장본 = 업무 담당자가 확인 후 저장한 최신본)이 이긴다.
    API 를 못 찾은 화살표(api: null)와 조회는 경로에 쓸 수 없어 뺀다 — 그 사실은 notes 로 돌려준다.
    """
    by: dict[str, StateGraph] = {}
    notes: list[str] = []
    for p in map(Path, paths):
        files = sorted(p.glob("*.yaml")) if p.is_dir() else ([p] if p.exists() else [])
        for f in files:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            if "graph" not in raw or "code_group" not in raw:
                continue
            ts = raw.get("transitions") or []
            keep = [t for t in ts if t.get("api")]
            if len(keep) < len(ts):
                notes.append(f"{raw['graph']['id']}: API 를 못 찾은 화살표 {len(ts) - len(keep)}개는 경로에서 뺌 ({f.name})")
            raw = dict(raw, transitions=keep, lookups=[lk for lk in raw.get("lookups") or [] if lk.get("api")])
            g = graph_from_dict(raw)
            by[g.graph_id] = g
    return list(by.values()), notes


def graph_from_dict(raw: dict[str, Any]) -> StateGraph:
    """knowledge 형식 dict → 그래프. 사람이 쓴 yaml · LLM 추출 결과가 같은 형식을 쓴다."""
    g, cg = raw["graph"], raw["code_group"]
    codes: dict[str, str] = {str(k): v for k, v in cg["codes"].items()}

    lookups: dict[str, Lookup] = {}
    for lk in raw.get("lookups") or []:
        item = Lookup(api_id=lk["api"], selector={k: str(v) for k, v in lk["selector"].items()},
                      states=[str(s) for s in lk["states"]])
        for s in item.states:
            lookups.setdefault(s, item)

    edges = []
    for t in raw.get("transitions") or []:
        sel = {k: str(v) for k, v in (t.get("selector") or {}).items()}
        tag = ",".join(sel.values())
        edges.append(Edge(id=f"{g['id']}:{t['from']}>{t['to']}" + (f":{tag}" if tag else ""),
                          kind=t.get("kind", "api"), name=t["name"], from_code=str(t["from"]),
                          to_code=str(t["to"]), api_id=t.get("api"), selector=sel,
                          source=t.get("source", "knowledge")))

    nodes = [StateNode(code=c, name=n, lookup=lookups.get(c)) for c, n in codes.items()]
    graph = StateGraph(graph_id=g["id"], name=g["name"], domain=g["domain"], entity=g["entity"],
                       state_field=g.get("state_field"), entry_states=[str(s) for s in g.get("entry_states", [])],
                       verify_key_fields=g.get("verify_key_fields", []), nodes=nodes, edges=edges)
    _mark_stages(graph)
    return graph


def _mark_stages(graph: StateGraph) -> None:
    """진입 상태에서 API 간선으로 몇 단계 떨어졌는지. 단계가 줄어드는 간선은 reverse(취소 · 반려)."""
    stage: dict[str, int] = {s: 0 for s in graph.entry_states}
    q = deque(graph.entry_states)
    while q:
        c = q.popleft()
        for e in graph.out_edges(c):
            if e.to_code not in stage:
                stage[e.to_code] = stage[c] + 1
                q.append(e.to_code)
    for n in graph.nodes:
        n.stage = stage.get(n.code)
    for e in graph.edges:
        a, b = stage.get(e.from_code), stage.get(e.to_code)
        e.reverse = a is not None and b is not None and b < a


def validate_graph(graph: StateGraph, metadata: list[dict[str, Any]],
                   operations: list[dict[str, Any]]) -> list[dict[str, str]]:
    """문제 목록. level: error(빌드 실패) · warn(검수) · info(참고)."""
    issues: list[dict[str, str]] = []
    meta = {m["api_id"]: m for m in metadata}
    req_fields = {o["api_id"]: {f["name"] for f in o["request_fields"]} for o in operations}
    codes = {n.code for n in graph.nodes}

    def add(level, where, msg):
        issues.append({"level": level, "where": where, "message": msg})

    def check_selector(where, api_id, selector):
        """간선 · 조회의 구분값이 API Metadata selectors 에 있는지 — API 지식은 Metadata 가 원본."""
        sels = {s["field"]: s for s in (meta[api_id].get("selectors") or [])}
        for f, v in selector.items():
            if f == graph.state_field:          # 상태 필드로 바로 거르는 조회 — 값은 상태 코드라 구분값 목록에 없다
                continue
            s = sels.get(f)
            if s is None:
                add("warn", where, f"구분값 {f} 가 API Metadata selectors 에 없음")
            elif v not in {x["value"] for x in s["values"]}:
                add("error" if s.get("complete") else "warn", where,
                    f"구분값 {f}={v} 가 API Metadata selectors 에 없음" + ("" if s.get("complete") else " (값 목록 미완성)"))

    for s in graph.entry_states:
        if s not in codes:
            add("error", "entry_states", f"진입 상태 {s} 가 코드 목록에 없음")
    for e in graph.edges:
        for c in (e.from_code, e.to_code):
            if c not in codes:
                add("error", e.id, f"상태 {c} 가 코드 목록에 없음")
        if e.kind != "api":
            continue
        m = meta.get(e.api_id or "")
        if not m:
            add("error", e.id, f"API {e.api_id} 가 API Metadata 에 없음")
            continue
        if m["kind"] != "write":
            add("error", e.id, f"상태를 바꾸는 간선인데 API 가 조회({m['kind']})로 분류됨")
        for f in e.selector:
            if f not in req_fields.get(e.api_id, set()):
                add("error", e.id, f"선택값 필드 {f} 가 API 요청에 없음")
        check_selector(e.id, e.api_id, e.selector)
        if not m.get("tool_enabled", True):
            add("warn", e.id, "API 가 사용 안 함(tool_enabled=false) 상태")

    seen_lookups = set()
    for n in graph.nodes:
        lk = n.lookup
        if not lk or id(lk) in seen_lookups:
            continue
        seen_lookups.add(id(lk))
        m = meta.get(lk.api_id)
        if not m:
            add("error", f"lookup:{lk.api_id}", "조회 API 가 API Metadata 에 없음")
            continue
        if m["kind"] != "read":
            add("error", f"lookup:{lk.api_id}", "조회 방법인데 API 가 쓰기로 분류됨")
        for f in lk.selector:
            if f not in req_fields.get(lk.api_id, set()):
                add("error", f"lookup:{lk.api_id}", f"선택값 필드 {f} 가 API 요청에 없음")
        check_selector(f"lookup:{lk.api_id}", lk.api_id, lk.selector)
        for s in lk.states:
            if s not in codes:
                add("warn", f"lookup:{lk.api_id}:{lk.selector}", f"조회 대상 상태 {s} 가 코드 목록에 없음 — 확인 필요")

    unreachable = [n for n in graph.nodes if n.stage is None and n.lookup is None]
    if unreachable:
        add("info", "nodes", f"API 로 만들 수도, 조회로 찾을 수도 없는 상태 {len(unreachable)}개: "
            + ", ".join(f"{n.code} {n.name}" for n in unreachable))
    return issues
