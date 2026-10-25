"""자연어 → 목표(Goal). LLM 은 목표 상태만 고르고, 호출 순서는 고르지 않는다.

- 상태는 그래프의 상태 이름 목록(Literal) 안에서만 고를 수 있다 — 없는 상태를 지어내지 못한다
- 근거 구절(source_phrases)이 원문에 없으면 환각으로 보고 버린다
- 표현하지 못한 조건은 unsupported 에 남긴다 — 조용히 버리지 않는다
- 만들 수 있는지는 판단하지 않는다 — 그건 그래프가 증명한다 (예: 결제완료는 경로 계산에서 거절)
"""
from __future__ import annotations

import os
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, create_model

from tap.graph.model import StateGraph
from tap.graph.plan import Goal

# (messages, 응답 스키마) → 스키마 인스턴스. 테스트에서는 가짜로 바꿔 끼운다.
LLMParse = Callable[[list[dict[str, str]], type[BaseModel]], BaseModel]


class GoalError(ValueError):
    pass


def goal_schema(graph: StateGraph) -> type[BaseModel]:
    names = tuple(n.name for n in graph.nodes)
    State = Literal[names]  # type: ignore[valid-type]
    return create_model(
        "GoalOut",
        target=(State, Field(description="요청이 끝났을 때 데이터가 있어야 할 상태")),
        must_pass=(list[State], Field(default_factory=list,
                                      description="target 전에 반드시 거쳐야 할 상태. 예: '배송완료된 주문을 배송완료 취소' → 배송완료")),
        count=(int, Field(default=1, ge=1, le=100, description="건수. 말하지 않으면 1")),
        source_phrases=(list[str], Field(description="target · must_pass · count 를 정한 근거 — 요청 원문에서 그대로 복사한 구절")),
        unsupported=(list[str], Field(default_factory=list, description="이 그래프로 표현할 수 없는 조건 (예: 특정 브랜드, 금액)")),
    )


def build_messages(utterance: str, graph: StateGraph) -> list[dict[str, str]]:
    states = "\n".join(f"- {n.name} ({n.code})" for n in graph.nodes)
    actions = "\n".join(f"- {e.name}: {graph.node(e.from_code).name} → {graph.node(e.to_code).name}"
                        for e in graph.edges if e.kind == "api")
    system = f"""당신은 테스트 데이터 요청을 '목표 상태'로 바꾸는 역할만 한다.
대상: {graph.entity} ({graph.name} 그래프)

[상태 목록 — 이 이름 중에서만 고른다]
{states}

[참고: 상태를 바꾸는 동작]
{actions}

규칙
1. target 은 요청이 끝났을 때 {graph.entity}가 있어야 할 상태다.
2. '…된 {graph.entity}를 ○○ 취소' 처럼 어떤 상태를 거쳤다가 되돌리는 요청은,
   되돌린 뒤의 상태를 target 으로, 거쳐야 하는 상태를 must_pass 로 둔다. 동작 목록을 보고 판단한다.
3. count 는 요청의 건수. 없으면 1.
4. source_phrases 에는 판단 근거가 된 구절을 요청 원문에서 글자 그대로 복사한다.
5. 만들 수 있는지는 판단하지 않는다. 요청이 가리키는 상태를 그대로 고른다.
6. 상태 목록으로 표현할 수 없는 조건은 unsupported 에 적는다."""
    return [{"role": "system", "content": system}, {"role": "user", "content": utterance}]


def openai_parse(model: str | None = None) -> LLMParse:
    """OpenAI Structured Output. 키 · 모델은 .env (OPENAI_API_KEY · OPENAI_DEFAULT_MODEL)."""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    client = OpenAI()
    use = model or os.environ.get("OPENAI_DEFAULT_MODEL")
    if not use:
        raise GoalError("OPENAI_DEFAULT_MODEL 이 .env 에 없습니다")

    def parse(messages: list[dict[str, str]], schema: type[BaseModel]) -> BaseModel:
        r = client.chat.completions.parse(model=use, messages=messages, response_format=schema)
        out = r.choices[0].message.parsed
        if out is None:
            raise GoalError(f"모델이 응답을 거부하거나 형식을 지키지 못함: {r.choices[0].message.refusal}")
        return out
    return parse


def _norm(s: str) -> str:
    return "".join(s.split())


def to_goal(out: BaseModel | dict[str, Any], utterance: str, graph: StateGraph) -> Goal:
    """LLM 출력을 검증해 Goal 로 바꾼다. 근거 구절이 원문에 없으면 거절."""
    d = out.model_dump() if isinstance(out, BaseModel) else dict(out)
    if not d.get("source_phrases"):
        raise GoalError("근거 구절이 없습니다")
    missing = [p for p in d["source_phrases"] if _norm(p) not in _norm(utterance)]
    if missing:
        raise GoalError(f"근거 구절이 원문에 없습니다(환각 의심): {missing}")
    code = graph.code_of(d["target"])
    if code is None:
        raise GoalError(f"알 수 없는 상태: {d['target']}")
    must = [graph.code_of(n) for n in d.get("must_pass") or []]
    if None in must:
        raise GoalError(f"알 수 없는 상태: {d.get('must_pass')}")
    return Goal(graph_id=graph.graph_id, target=code, must_pass=[m for m in must if m != code],
                count=int(d.get("count") or 1), source_phrases=d["source_phrases"],
                unsupported=d.get("unsupported") or [])


def extract_goal(utterance: str, graph: StateGraph, llm: LLMParse) -> Goal:
    out = llm(build_messages(utterance, graph), goal_schema(graph))
    return to_goal(out, utterance, graph)
