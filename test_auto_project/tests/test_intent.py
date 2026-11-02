"""업무 의도 분석 — 자연어 → 업무 목록 (LLM 없이, 가짜 LLM 출력으로 검사 규칙을 본다). 그래프는 보지 않는다."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from tap.catalog.build import load_domain_rules
from tap.cli import analyze_intent
from tap.goal.extract import GoalError, intent_messages, task_schema, to_task_plan

ROOT = Path(__file__).resolve().parents[1]
Q1 = "가격이 50000원인 설치상품을 만들고 주문한 뒤 배송완료까지 처리해줘"


@pytest.fixture(scope="module")
def domains():
    return load_domain_rules(ROOT / "data/config/domains.yaml")["domains"]


def task(**kw):
    t = {"sequence": 1, "domain": "OD", "origin": "기존", "action": "배송완료", "conditions": "c", "constraints": [],
         "depends_on": [], "count": 1, "source_phrases": ["배송완료"]}
    return {**t, **kw}


def plan(utterance, *tasks, unresolved=()):
    return {"original_question": utterance, "tasks": list(tasks), "unresolved": list(unresolved)}


EX1 = plan(Q1,
           task(sequence=1, domain="PD", origin="신규", action="상품생성",
                constraints=[{"name": "가격", "value": "50000원", "role": "설정값", "source_phrase": "가격이 50000원인"},
                             {"name": "상품 종류", "value": "설치상품", "role": "설정값", "source_phrase": "설치상품"}],
                source_phrases=["가격이 50000원인 설치상품을 만들고"]),
           task(sequence=2, origin="신규", depends_on=[1], source_phrases=["주문한 뒤 배송완료까지 처리해줘"]))


def test_messages_show_domains_not_graphs(domains):
    sys_ = intent_messages("x", domains)[0]["content"]
    assert "- OD: 주문" in sys_ and "- PD: 상품" in sys_
    assert "ORD_STAT_GBCD" not in sys_.split("[예시]")[0] and "그래프 목록" not in sys_   # 그래프는 경로 탐색 단계가 본다


def test_schema_has_no_graph_fields_and_limits_values(domains):
    S = task_schema(domains)
    S.model_validate(EX1)
    fields = set(S.model_fields["tasks"].annotation.__args__[0].model_fields)
    assert not fields & {"graph_id", "target_state", "must_pass"}
    for bad in (task(domain="XX"), task(origin="생성"), task(count=0), task(constraints=[{"name": "a", "value": "1", "role": "x", "source_phrase": "a"}])):
        with pytest.raises(ValidationError):
            S.model_validate(plan(Q1, bad))


def test_example_plan_passes(domains):
    r, notes = to_task_plan(task_schema(domains).model_validate(EX1), Q1)
    assert notes == []
    a, b = r.tasks
    assert (a.domain, a.origin, a.action) == ("PD", "신규", "상품생성")
    assert [(c.name, c.value, c.role) for c in a.constraints] == [("가격", "50000원", "설정값"), ("상품 종류", "설치상품", "설정값")]
    assert (b.domain, b.depends_on) == ("OD", [1])


def test_code_values_kept():
    q = "협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘"
    t = task(domain="PD", action="브랜드코드변경", source_phrases=[q],
             constraints=[{"name": "협력사코드", "value": "000000", "role": "대상조건", "source_phrase": "협력사코드가 000000인"},
                          {"name": "브랜드코드", "value": "1234", "role": "설정값", "source_phrase": "브랜드코드를 1234로"}])
    r, _ = to_task_plan(plan(q, t), q)
    assert r.tasks[0].constraints[0].value == "000000"                                  # 앞자리 0 그대로


@pytest.mark.parametrize("bad, msg", [
    (task(source_phrases=["가격이 5만원인"]), "환각 의심"),                                  # 원문에 없는 근거
    (task(source_phrases=[Q1], constraints=[{"name": "가격", "value": "60000원", "role": "설정값",
                                              "source_phrase": "가격이 60000원인"}]), "환각 의심"),
    (task(source_phrases=[]), "근거 구절이 없습니다"),
])
def test_rejects(bad, msg):
    with pytest.raises(GoalError, match=msg):
        to_task_plan(plan(Q1, bad), Q1)


def test_rejects_bad_order():
    ok = task(source_phrases=[Q1])
    with pytest.raises(GoalError, match="빈틈없지"):
        to_task_plan(plan(Q1, ok, {**ok, "sequence": 3}), Q1)
    with pytest.raises(GoalError, match="앞 업무가 아닙니다"):
        to_task_plan(plan(Q1, {**ok, "depends_on": [2]}, {**ok, "sequence": 2}), Q1)


def test_fixes_question():
    r, notes = to_task_plan(plan("다른 문장", task()), "배송완료 처리")
    assert r.original_question == "배송완료 처리" and any("original_question" in n for n in notes)


def test_not_a_request():
    r, _ = to_task_plan(plan("주문상태 코드가 몇 개야?"), "주문상태 코드가 몇 개야?")
    assert r.tasks == [] and r.unresolved == []


def test_analyze_intent_reads_domains():
    seen = {}

    def llm(messages, schema):
        seen["sys"] = messages[0]["content"]
        return schema.model_validate(EX1)
    r = analyze_intent(Q1, llm=llm)
    assert len(r["plan"].tasks) == 2 and "- DS: 물류/SCM" in seen["sys"]
