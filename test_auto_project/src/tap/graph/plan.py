"""경로 계산 — LLM 이 아니라 그래프 탐색이 호출 순서를 정한다. 같은 목표는 항상 같은 경로.

전략
  A. advance (기본) — 진입 상태(예: 25 출고대기)의 기존 데이터를 조회로 찾아 API 로 진행시킨다
  B. lookup  (대안) — 조회 가능한 상태 중 쓰기 호출이 가장 적은 곳에서 시작한다
                      (목표 상태를 바로 조회할 수 있으면 쓰기 0회)
둘 다 안 되면 거절하고 이유를 남긴다.
"""
from __future__ import annotations

from collections import deque
from typing import Literal

from pydantic import BaseModel, Field

from tap.graph.model import Edge, Lookup, StateGraph

MAX_DEPTH = 12


class Goal(BaseModel):
    """자연어에서 뽑은 목표. LLM 은 이것만 만든다."""

    graph_id: str
    target: str                                 # 마지막에 있어야 할 상태 코드
    must_pass: list[str] = Field(default_factory=list)   # 그 전에 거쳐야 할 상태 코드 (예: 배송완료 후 취소)
    count: int = 1
    source_phrases: list[str] = Field(default_factory=list)   # 근거가 된 원문 구절
    unsupported: list[str] = Field(default_factory=list)      # 표현하지 못한 조건 — 조용히 버리지 않는다


class Path(BaseModel):
    strategy: Literal["advance", "lookup"]
    start: str                                  # 조회로 확보할 시작 상태
    lookup: Lookup
    edges: list[Edge]
    states: list[str]                           # 지나가는 상태 순서 (시작 포함)

    @property
    def writes(self) -> int:
        return len(self.edges)


class PlanResult(BaseModel):
    status: Literal["ok", "rejected"]
    primary: Path | None = None
    alternative: Path | None = None
    reason: str | None = None


def search(graph: StateGraph, start: str, goal: Goal) -> tuple[list[Edge], list[str]] | None:
    """start 에서 goal 까지 가장 짧은 API 간선 순서. must_pass 를 모두 거친 뒤 target 에 있어야 한다.

    탐색 상태 = (현재 상태, 거친 must_pass 집합) — 같은 상태라도 거친 것이 다르면 다시 방문할 수 있다
    (예: 45 → 50 → 45 '배송완료 후 취소').
    """
    need = frozenset(goal.must_pass)
    first = (start, frozenset({start}) & need)
    q = deque([(first, [], [start])])
    seen = {first}
    while q:
        (code, passed), edges, states = q.popleft()
        if code == goal.target and passed == need:
            return edges, states
        if len(edges) >= MAX_DEPTH:
            continue
        for e in graph.out_edges(code):
            nxt = (e.to_code, passed | (frozenset({e.to_code}) & need))
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, edges + [e], states + [e.to_code]))
    return None


def _best(graph: StateGraph, starts: list[str], goal: Goal, strategy) -> Path | None:
    found: list[Path] = []
    for s in starts:
        node = graph.node(s)
        if node.lookup is None:
            continue
        r = search(graph, s, goal)
        if r:
            found.append(Path(strategy=strategy, start=s, lookup=node.lookup, edges=r[0], states=r[1]))
    # 쓰기가 적은 순, 같으면 앞 단계에서 시작하는 쪽 (더 '만든' 데이터에 가깝다)
    found.sort(key=lambda p: (p.writes, graph.node(p.start).stage if graph.node(p.start).stage is not None else 99))
    return found[0] if found else None


def plan(graph: StateGraph, goal: Goal) -> PlanResult:
    codes = {n.code for n in graph.nodes}
    for c in [goal.target, *goal.must_pass]:
        if c not in codes:
            return PlanResult(status="rejected", reason=f"그래프 {graph.graph_id} 에 없는 상태: {c}")

    a = _best(graph, graph.entry_states, goal, "advance")
    b = _best(graph, [n.code for n in graph.nodes if n.lookup], goal, "lookup")
    if b and a and (b.start, [e.id for e in b.edges]) == (a.start, [e.id for e in a.edges]):
        b = None                                # 대안이 기본과 같으면 따로 안내하지 않는다
    if a:
        return PlanResult(status="ok", primary=a, alternative=b)
    if b:
        return PlanResult(status="ok", primary=b, reason="진입 상태에서 API 로 갈 수 없어 기존 데이터를 찾아 쓰는 방식으로 계획함")

    t = graph.node(goal.target)
    why = [f"{t.name}({t.code}) 은(는)"]
    if t.stage is None:
        entry = ", ".join(f"{graph.node(s).name}({s})" for s in graph.entry_states)
        why.append(f"API 로 만들 수 없는 상태입니다 — 우리가 다룰 수 있는 첫 상태는 {entry} 이고, 그 앞은 외부(고객 주문 · 결제 등)에서 생깁니다.")
    else:
        why.append("목표 조건(거쳐야 할 상태)을 만족하는 API 경로가 없습니다.")
    if t.lookup is None:
        why.append("이 상태를 조회로 찾는 방법도 등록되어 있지 않습니다.")
    return PlanResult(status="rejected", reason=" ".join(why))
