"""자연어 → 목표(Goal) · 업무 목록(TaskPlan). LLM 은 목표 상태만 고르고, 호출 순서는 고르지 않는다.

- extract_goal: 그래프 하나 안에서 목표 상태 (지금 시나리오 생성이 쓰는 것)
- extract_tasks: 요청을 업무(task) 여러 개로 나누고 업무마다 도메인 · 그래프 · 목표 상태 · 제약 (업무 의도 분석)

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
    states = "\n".join(f"- {n.name} ({n.code})" + (f" · 다른 표현: {', '.join(n.synonyms)}" if n.synonyms else "")
                       for n in graph.nodes)
    actions = "\n".join(f"- {e.name}: {graph.node(e.from_code).name} → {graph.node(e.to_code).name}"
                        for e in graph.edges if e.kind == "api")
    system = f"""당신은 테스트 데이터 요청을 '목표 상태'로 바꾸는 역할만 한다.
대상: {graph.entity} ({graph.name} 그래프)

[상태 목록 — 이 이름 중에서만 고른다. '다른 표현'으로 말해도 고르는 값은 앞의 상태 이름]
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
6. 상태 목록으로 표현할 수 없는 조건은 unsupported 에 적는다.
7. 요청이 상태 이름 대신 '다른 표현'을 쓰면 그 상태로 본다 (예: 다른 표현에 '발송된' 이 있으면 출고)."""
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


def graph_schema(graphs: list[StateGraph]) -> type[BaseModel]:
    ids = tuple(g.graph_id for g in graphs) + ("없음",)
    return create_model("GraphChoice",
                        graph_id=(Literal[ids], Field(description="요청이 말하는 대상 · 상태에 맞는 그래프. 맞는 게 없으면 '없음'")),  # type: ignore[valid-type]
                        reason=(str, Field(description="고른 이유 — 요청의 어떤 말이 어떤 그래프의 대상 · 상태와 맞는지")))


def graph_messages(utterance: str, graphs: list[StateGraph]) -> list[dict[str, str]]:
    lines = []
    for g in graphs:
        states = ", ".join(n.name + (f"({'/'.join(n.synonyms)})" if n.synonyms else "") for n in g.nodes)
        lines.append(f"- {g.graph_id}: {g.name} — 대상 {g.entity} · 상태 {states}")
    system = f"""당신은 테스트 데이터 요청이 어떤 상태 그래프에 해당하는지 고르는 역할만 한다.
그래프 하나 = 어떤 대상의 상태 코드 그룹 하나다.

[그래프 목록]
{chr(10).join(lines)}

규칙
1. 요청이 말하는 대상(주문 · 상품 …)과 상태가 들어 있는 그래프 하나를 고른다.
2. 맞는 그래프가 없으면 '없음'을 고른다. 억지로 고르지 않는다.
3. reason 에 요청의 어떤 말 때문에 골랐는지 적는다."""
    return [{"role": "system", "content": system}, {"role": "user", "content": utterance}]


def choose_graph(utterance: str, graphs: list[StateGraph], llm: LLMParse) -> tuple[StateGraph | None, str]:
    """요청에 맞는 그래프 고르기. 그래프가 하나뿐이면 묻지 않는다."""
    if len(graphs) == 1:
        return graphs[0], "그래프가 하나뿐"
    out = llm(graph_messages(utterance, graphs), graph_schema(graphs)).model_dump()
    g = next((x for x in graphs if x.graph_id == out["graph_id"]), None)
    return g, out["reason"]


def extract_goal(utterance: str, graph: StateGraph, llm: LLMParse) -> Goal:
    out = llm(build_messages(utterance, graph), goal_schema(graph))
    return to_goal(out, utterance, graph)


# ─── 업무 의도 분석 — 자연어 → 업무(task) 목록 ─────────────────────────────────────────
# 업무 하나 = 대상 데이터 하나(상품 하나, 주문 하나 …)를 원하는 모습으로 만드는 일.
# 도메인 · 그래프 · 상태는 목록(Literal) 안에서만 고르고, 근거 구절 · 상태 소속 · 순서는 받은 뒤 코드로 다시 본다.
# 경로(어느 상태에서 출발해 무엇을 호출할지)와 API 는 고르지 않는다 — 다음 단계(경로 탐색 · API 선택)가 한다.

ORIGIN = ("신규", "기존")
ROLE = ("대상조건", "설정값")


class Constraint(BaseModel):
    name: str = Field(description="요청에 나온 업무 용어 그대로 (예: 가격, 협력사코드). API 필드명으로 바꾸지 않음")
    value: str = Field(description="요청의 값 그대로. 숫자 · 코드를 바꾸지 않음")
    role: Literal[ROLE] = Field(description="찾을 데이터의 조건 / 만들거나 바꿀 값")  # type: ignore[valid-type]
    source_phrase: str = Field(description="요청 원문에서 그대로 복사한 구절")


class Task(BaseModel):
    sequence: int
    domain: str                                 # 대문자 도메인 코드 (PD · OD …)
    origin: Literal[ORIGIN]                     # type: ignore[valid-type]
    action: str
    graph_id: str | None
    target_state: str | None                    # 상태 이름 — 코드는 graph.code_of 로
    must_pass: list[str]
    conditions: str
    constraints: list[Constraint]
    depends_on: list[int]
    count: int
    source_phrases: list[str]


class TaskPlan(BaseModel):
    original_question: str
    tasks: list[Task]
    unresolved: list[str]


def task_schema(domains: dict[str, str], graphs: list[StateGraph]) -> type[BaseModel]:
    """LLM 이 채울 형식. 모든 칸을 필수로 둔다 — 빠뜨림과 null 이 섞이지 않게."""
    Domain = Literal[tuple(k.upper() for k in domains)]  # type: ignore[valid-type]
    if graphs:
        GraphId = Literal[tuple(g.graph_id for g in graphs)] | None  # type: ignore[valid-type]
        State = Literal[tuple(dict.fromkeys(n.name for g in graphs for n in g.nodes))]  # type: ignore[valid-type]
        Target = State | None
    else:                                       # 그래프가 없으면 graph_id · 상태는 비워 둘 수밖에 없다
        GraphId = Target = type(None)
        State = Literal[("-",)]  # type: ignore[valid-type]
    TaskOut = create_model(
        "TaskOut",
        sequence=(int, Field(ge=1, description="실행 순서. 앞 업무 결과가 필요한 업무가 뒤")),
        domain=(Domain, Field(description="graph_id 가 있으면 그 그래프의 도메인, 없으면 대상 데이터의 주인 도메인")),
        origin=(Literal[ORIGIN], Field(description="새로 만드는 데이터 / 이미 있는 데이터")),  # type: ignore[valid-type]
        action=(str, Field(description="그래프의 동작 · 상태 이름 그대로, 없으면 '대상+동작' 명사형")),
        graph_id=(GraphId, Field(description="다루는 상태 그래프. 없으면 null")),
        target_state=(Target, Field(description="끝났을 때의 상태. 요청이 말하지 않거나 맞는 상태가 없으면 null")),
        must_pass=(list[State], Field(description="target 전에 거쳐야 할 상태. 되돌리기 요청에서만, 그 밖에는 []")),
        conditions=(str, Field(description="사람이 읽을 업무 요약 한 문장")),
        constraints=(list[Constraint], Field(description="요청에 나온 조건 하나하나. 상태는 넣지 않음")),
        depends_on=(list[int], Field(description="결과를 넘겨받는 앞 업무의 sequence")),
        count=(int, Field(ge=1, le=100, description="건수. 말하지 않으면 1")),
        source_phrases=(list[str], Field(description="이 업무를 정한 구절. 요청 원문에서 그대로 복사")),
    )
    return create_model(
        "TaskPlanOut",
        original_question=(str, Field(description="요청 원문 그대로")),
        tasks=(list[TaskOut], Field(description="업무 목록. 테스트 데이터 요청이 아니면 []")),
        unresolved=(list[str], Field(description="업무로 표현하지 못한 조건 · 애매한 부분")),
    )


def domains_text(domains: dict[str, str]) -> str:
    return "\n".join(f"- {k.upper()}: {v}" for k, v in domains.items())


def graphs_text(graphs: list[StateGraph]) -> str:
    """그래프마다 상태 이름 · 동작 이름. 코드는 주지 않는다 — LLM 은 이름만 고르고 코드로 바꾸는 건 코드가 한다."""
    if not graphs:
        return "(등록된 그래프 없음)"
    lines = []
    for g in graphs:
        states = ", ".join(n.name + (f"(다른 표현: {'/'.join(n.synonyms)})" if n.synonyms else "") for n in g.nodes)
        acts = ", ".join(f"{e.name}({g.node(e.from_code).name}→{g.node(e.to_code).name})"
                         for e in g.edges if e.kind == "api")
        lines += [f"- {g.graph_id} {g.name} | 도메인 {g.domain.upper()} | 대상 {g.entity}",
                  f"  상태: {states}", f"  동작: {acts or '(아직 없음)'}"]
    return "\n".join(lines)


INTENT_EXAMPLES = """요청: 가격이 50000원인 설치상품을 만들고 주문한 뒤 배송완료까지 처리해줘
{"tasks":[
 {"sequence":1,"domain":"PD","origin":"신규","action":"상품생성","graph_id":"SLITM_APRVL_GBCD","target_state":null,"must_pass":[],
  "conditions":"가격이 50000원인 설치상품을 신규 생성한다.",
  "constraints":[{"name":"가격","value":"50000원","role":"설정값","source_phrase":"가격이 50000원인"},
                 {"name":"상품 종류","value":"설치상품","role":"설정값","source_phrase":"설치상품"}],
  "depends_on":[],"count":1,"source_phrases":["가격이 50000원인 설치상품을 만들고"]},
 {"sequence":2,"domain":"OD","origin":"신규","action":"배송완료","graph_id":"ORD_STAT_GBCD","target_state":"배송완료","must_pass":[],
  "conditions":"1번 업무에서 생성한 상품으로 주문을 생성해 배송완료 상태로 만든다.",
  "constraints":[],"depends_on":[1],"count":1,"source_phrases":["주문한 뒤 배송완료까지 처리해줘"]}],
 "unresolved":[]}

요청: 배송완료된 주문 3건을 배송완료 취소시켜줘
{"tasks":[
 {"sequence":1,"domain":"OD","origin":"기존","action":"배송완료취소","graph_id":"ORD_STAT_GBCD","target_state":"출고","must_pass":["배송완료"],
  "conditions":"배송완료 상태인 주문 3건을 배송완료 취소한다.",
  "constraints":[],"depends_on":[],"count":3,"source_phrases":["배송완료된 주문 3건을 배송완료 취소시켜줘"]}],
 "unresolved":[]}

요청: 협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘
{"tasks":[
 {"sequence":1,"domain":"PD","origin":"기존","action":"브랜드코드변경","graph_id":null,"target_state":null,"must_pass":[],
  "conditions":"협력사코드가 000000인 상품 하나의 브랜드코드를 1234로 바꾼다.",
  "constraints":[{"name":"협력사코드","value":"000000","role":"대상조건","source_phrase":"협력사코드가 000000인"},
                 {"name":"브랜드코드","value":"1234","role":"설정값","source_phrase":"브랜드코드를 1234로"}],
  "depends_on":[],"count":1,"source_phrases":["협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘"]}],
 "unresolved":[]}"""


def intent_messages(utterance: str, domains: dict[str, str], graphs: list[StateGraph]) -> list[dict[str, str]]:
    system = f"""당신은 테스트 데이터 생성 요청을 '업무(task)' 단위로 나누는 역할만 한다.
업무 하나 = 대상 데이터 하나(상품 하나, 주문 하나 …)를 원하는 모습으로 만드는 일이다.
API 를 고르거나 호출 순서를 정하지 않는다. 실제로 만들 수 있는지도 판단하지 않는다 — 그건 다음 단계가 한다.

[업무 도메인 목록 — domain 은 이 코드 중에서만 고른다]
{domains_text(domains)}

[상태 그래프 목록 — 그래프 하나 = 한 대상의 상태 코드 그룹. 그래프의 도메인 = 그 상태를 책임지는 도메인]
{graphs_text(graphs)}

규칙
[업무 나누기]
1. 같은 대상 데이터에 대한 일은 업무 하나다. 새로 만들어서 여러 상태를 거쳐 가도 하나다.
   예) "주문을 만들어서 배송완료까지" → 업무 1개
2. 대상이 다르면 업무를 나눈다. 예) "상품을 만들고 그 상품으로 주문" → 상품 1개 + 주문 1개
3. sequence 는 실행 순서다. 앞 업무의 결과가 필요한 업무가 뒤에 온다. 1부터 빈틈없이 매긴다.
4. depends_on 에는 이 업무가 결과를 넘겨받는 앞 업무의 sequence 를 적는다. 없으면 [].

[origin]
5. 요청이 그 대상을 새로 만들라고 하면 신규다. (만들어, 생성, 등록, 신규, "주문해줘"처럼 대상을 만드는 동사)
6. 그 밖에는 기존이다 — 이미 있는 데이터를 찾아서 쓰거나 바꾸는 일.
   예) "배송완료된 주문을 취소", "출고된 주문 하나 줘", "상품 하나의 브랜드코드를 바꿔줘"

[graph_id · target_state · must_pass]
7. 업무가 그래프에 있는 상태를 다루면 graph_id 에 그 그래프를 고른다. 다루지 않으면 null.
   신규 업무는 대상이 가진 상태 그래프를 고른다. (예: 상품 생성 → 판매상품승인 그래프)
8. target_state 는 업무가 끝났을 때 데이터가 있어야 할 상태다. graph_id 그래프의 상태 이름 중에서 고른다.
   - 동작을 말했으면 그 동작의 도착 상태다. (예: 배송완료취소 → 출고)
   - '다른 표현'으로 말해도 원래 상태 이름을 쓴다.
   - 요청이 상태를 말하지 않으면 null. 업무상 필요해 보여도 추측해서 채우지 않는다. (예: "상품 만들어줘" → null)
   - 요청이 말한 상태 · 동작이 그 그래프에 없으면 null 로 두고 unresolved 에 적는다. 비슷한 다른 상태로 바꾸지 않는다.
9. must_pass 는 target_state 전에 반드시 거쳐야 하는 상태다. 어떤 상태를 거쳤다가 되돌리는 요청에서만 쓴다.
   예) "배송완료된 주문을 배송완료 취소" → target_state 출고, must_pass [배송완료]. 그 밖에는 [].
10. graph_id 가 null 이면 target_state 는 null, must_pass 는 [] 이다.

[domain]
11. graph_id 가 있으면 그 그래프의 도메인이다.
12. graph_id 가 없으면 대상 데이터의 주인 도메인이다. (상품 → PD, 주문 → OD)

[action · conditions]
13. action 은 업무를 짧은 명사형으로 쓴다. 그래프의 동작 이름 · 상태 이름으로 말할 수 있으면 그 이름을 글자 그대로 쓴다.
    그래프에 없는 일은 '대상+동작'으로 쓴다. (상품생성, 브랜드코드변경)
14. conditions 는 업무 전체를 사람이 읽을 한 문장으로 쓴다. 앞 업무는 "n번 업무에서 생성한 ○○"처럼 가리킨다.

[constraints]
15. constraints 는 요청에 나온 조건 하나하나다. 상태는 넣지 않는다 (상태는 target_state · must_pass 에 있다).
    - name: 요청의 업무 용어 그대로 (가격, 협력사코드). API 필드명으로 바꾸지 않는다.
    - value: 요청의 값 그대로. 숫자 · 코드를 바꾸거나 반올림하지 않는다.
    - role: 찾을 데이터의 조건이면 대상조건, 만들거나 바꿀 값이면 설정값.
    - source_phrase: 그 조건이 나온 구절을 요청 원문에서 글자 그대로 복사한다.
16. 요청에 없는 값은 지어내지 않는다. 기본값이나 예시값을 넣지 않는다.

[count · 근거 · 그 밖]
17. count 는 요청의 건수. 말하지 않으면 1. "몇 개", "여러 건"처럼 애매하면 1로 두고 unresolved 에 적는다.
18. source_phrases 에는 이 업무를 정한 구절을 요청 원문에서 글자 그대로 복사한다. 요약하거나 고치지 않는다.
19. 업무로 표현하지 못한 조건이나 애매한 부분은 unresolved 에 적는다. 버리지 않는다.
20. 테스트 데이터를 만들거나 바꾸는 요청이 아니면 (질문, 조회만, 인사 등) tasks 를 빈 배열로 둔다.
21. original_question 에는 요청 원문을 글자 그대로 복사한다.

[예시 — 형식 설명용. 그래프 · 상태는 위 목록에 있는 것만 쓴다]
{INTENT_EXAMPLES}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": utterance}]


def to_task_plan(out: BaseModel | dict[str, Any], utterance: str,
                 graphs: list[StateGraph]) -> tuple[TaskPlan, list[str]]:
    """LLM 출력을 검사해 TaskPlan 으로. 스키마로 못 막는 것(상태가 그 그래프 것인지 · 근거 구절 · 순서)을 본다.

    틀리면 GoalError. 도메인이 그래프 도메인과 다르면 그래프 쪽으로 바로잡고 notes 에 남긴다.
    """
    d = out.model_dump() if isinstance(out, BaseModel) else dict(out)
    notes: list[str] = []
    if d.get("original_question") != utterance:
        notes.append("original_question 을 요청 원문으로 바꿈")
    by_id = {g.graph_id: g for g in graphs}
    tasks = sorted(d.get("tasks") or [], key=lambda t: t["sequence"])
    if [t["sequence"] for t in tasks] != list(range(1, len(tasks) + 1)):
        raise GoalError(f"sequence 가 1부터 빈틈없지 않습니다: {[t['sequence'] for t in tasks]}")
    for t in tasks:
        n = t["sequence"]
        bad = [x for x in t.get("depends_on") or [] if not 1 <= x < n]
        if bad:
            raise GoalError(f"{n}번 업무의 depends_on 이 앞 업무가 아닙니다: {bad}")
        phrases = (t.get("source_phrases") or []) + [c["source_phrase"] for c in t.get("constraints") or []]
        if not t.get("source_phrases"):
            raise GoalError(f"{n}번 업무에 근거 구절이 없습니다")
        missing = [p for p in phrases if _norm(p) not in _norm(utterance)]
        if missing:
            raise GoalError(f"{n}번 업무의 근거 구절이 원문에 없습니다(환각 의심): {missing}")
        g = by_id.get(t.get("graph_id")) if t.get("graph_id") else None
        if g is None:
            if t.get("graph_id"):
                raise GoalError(f"{n}번 업무: 알 수 없는 그래프 {t['graph_id']}")
            if t.get("target_state") or t.get("must_pass"):
                raise GoalError(f"{n}번 업무: 그래프 없이 상태를 골랐습니다 ({t.get('target_state')}, {t.get('must_pass')})")
            continue
        names = {x.name for x in g.nodes}
        wrong = [s for s in [t.get("target_state"), *(t.get("must_pass") or [])] if s and s not in names]
        if wrong:
            raise GoalError(f"{n}번 업무: {g.name} 그래프에 없는 상태 {wrong}")
        t["must_pass"] = [s for s in t.get("must_pass") or [] if s != t.get("target_state")]
        if t["domain"] != g.domain.upper():
            notes.append(f"{n}번 업무 domain {t['domain']} → {g.domain.upper()} ({g.name} 그래프의 도메인)")
            t["domain"] = g.domain.upper()
    plan_ = TaskPlan(original_question=utterance, tasks=[Task.model_validate(t) for t in tasks],
                     unresolved=d.get("unresolved") or [])
    return plan_, notes


def extract_tasks(utterance: str, domains: dict[str, str], graphs: list[StateGraph],
                  llm: LLMParse) -> tuple[TaskPlan, list[str]]:
    out = llm(intent_messages(utterance, domains, graphs), task_schema(domains, graphs))
    return to_task_plan(out, utterance, graphs)
