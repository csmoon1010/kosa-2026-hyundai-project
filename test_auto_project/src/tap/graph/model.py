"""상태 그래프 모델 — 그래프 하나 = 상태 코드 그룹 하나 (예: ORD_STAT_GBCD 주문상태).

간선 = API + 고정 선택값. 선택값(procGb 등)은 '어떤 동작을 할지' 고르는 스위치라
간선 정의에 고정하고, 자연어 · Agent · 실행 시 바꾼 값이 덮어쓰지 못한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Lookup(BaseModel):
    """그 상태의 데이터를 조회로 찾는 방법. 서버가 '마지막 상태'로 걸러 준다."""

    api_id: str
    selector: dict[str, str]                    # 예: {prgrGb: P0}
    states: list[str]                           # 이 조회로 나오는 상태 (여럿일 수 있음)


class StateNode(BaseModel):
    code: str
    name: str
    lookup: Lookup | None = None                # 조회로 찾을 수 있으면
    stage: int | None = None                    # 진입 상태에서 몇 번째 단계인지 (앞으로 가는 간선 기준)
    synonyms: list[str] = Field(default_factory=list)   # 자연어에서 이 상태를 가리키는 다른 표현 (State Vocabulary 동의어)


class Edge(BaseModel):
    id: str                                     # 예: ORD_STAT_GBCD:25>30:P1
    kind: Literal["api", "external"] = "api"
    name: str                                   # 출고진행
    from_code: str
    to_code: str
    api_id: str | None = None
    selector: dict[str, str] = Field(default_factory=dict)
    reverse: bool = False                       # 단계가 거꾸로 가는 간선 (취소 · 반려 등)
    source: str = "knowledge"                   # 근거 — knowledge(사람 확인) · spec · llm …


class StateGraph(BaseModel):
    graph_id: str
    name: str
    domain: str
    entity: str
    state_field: str | None = None
    entry_states: list[str] = Field(default_factory=list)
    verify_key_fields: list[str] = Field(default_factory=list)
    nodes: list[StateNode]
    edges: list[Edge]

    def node(self, code: str) -> StateNode:
        return next(n for n in self.nodes if n.code == code)

    def code_of(self, name: str) -> str | None:
        return next((n.code for n in self.nodes if n.name == name), None)

    def out_edges(self, code: str) -> list[Edge]:
        return [e for e in self.edges if e.from_code == code and e.kind == "api"]
