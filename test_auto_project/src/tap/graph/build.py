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
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
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
        for s in lk.states:
            if s not in codes:
                add("warn", f"lookup:{lk.api_id}:{lk.selector}", f"조회 대상 상태 {s} 가 코드 목록에 없음 — 확인 필요")

    unreachable = [n for n in graph.nodes if n.stage is None and n.lookup is None]
    if unreachable:
        add("info", "nodes", f"API 로 만들 수도, 조회로 찾을 수도 없는 상태 {len(unreachable)}개: "
            + ", ".join(f"{n.code} {n.name}" for n in unreachable))
    return issues
