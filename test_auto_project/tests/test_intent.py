"""업무 의도 분석 — 자연어 → 업무 목록 (LLM 없이, 가짜 LLM 출력으로 검사 규칙을 본다)."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from tap.catalog.build import load_domain_rules
from tap.cli import analyze_intent
from tap.goal.extract import GoalError, intent_messages, task_schema, to_task_plan
from tap.graph.build import load_graphs

ROOT = Path(__file__).resolve().parents[1]
Q1 = "가격이 50000원인 설치상품을 만들고 주문한 뒤 배송완료까지 처리해줘"


@pytest.fixture(scope="module")
def graphs():
    return load_graphs([ROOT / "data/graphs"])[0]


@pytest.fixture(scope="module")
def domains():
    return load_domain_rules(ROOT / "data/config/domains.yaml")["domains"]


def task(**kw):
    t = {"sequence": 1, "domain": "OD", "origin": "기존", "action": "배송완료", "graph_id": "ORD_STAT_GBCD",
         "target_state": "배송완료", "must_pass": [], "conditions": "c", "constraints": [], "depends_on": [],
         "count": 1, "source_phrases": ["배송완료"]}
    return {**t, **kw}


def plan(utterance, *tasks, unresolved=()):
    return {"original_question": utterance, "tasks": list(tasks), "unresolved": list(unresolved)}


def answer(d):
    """가짜 LLM — 스키마로 한 번 검증해서 돌려준다 (실제 Structured Output 과 같은 제약)."""
    return lambda messages, schema: schema.model_validate(d)


EX1 = plan(Q1,
           task(sequence=1, domain="PD", origin="신규", action="상품생성", graph_id="SLITM_APRVL_GBCD", target_state=None,
                constraints=[{"name": "가격", "value": "50000원", "role": "설정값", "source_phrase": "가격이 50000원인"},
                             {"name": "상품 종류", "value": "설치상품", "role": "설정값", "source_phrase": "설치상품"}],
                source_phrases=["가격이 50000원인 설치상품을 만들고"]),
           task(sequence=2, origin="신규", depends_on=[1], source_phrases=["주문한 뒤 배송완료까지 처리해줘"]))


def test_messages_show_domains_graphs_and_synonyms(graphs, domains):
    g = next(x for x in graphs if x.graph_id == "ORD_STAT_GBCD").model_copy(deep=True)
    g.node("45").synonyms = ["발송"]
    sys_ = intent_messages("x", domains, [g])[0]["content"]
    assert "- OD: 주문" in sys_ and "- PD: 상품" in sys_
    assert "- ORD_STAT_GBCD 주문상태 | 도메인 OD | 대상 주문" in sys_
    assert "출고(다른 표현: 발송)" in sys_ and "배송완료취소(배송완료→출고)" in sys_
    assert "(25)" not in sys_                                                       # 상태 코드는 주지 않는다
    assert "동작: (아직 없음)" in intent_messages("x", domains, graphs)[0]["content"]   # 화살표 없는 승인 그래프


def test_schema_limits_domain_graph_state(graphs, domains):
    S = task_schema(domains, graphs)
    S.model_validate(EX1)
    for bad in (task(domain="XX"), task(graph_id="NO_GRAPH"), task(target_state="구매확정"), task(origin="생성"),
                task(count=0)):
        with pytest.raises(ValidationError):
            S.model_validate(plan(Q1, bad))


def test_example_plan_passes(graphs, domains):
    r, notes = to_task_plan(task_schema(domains, graphs).model_validate(EX1), Q1, graphs)
    assert notes == []
    a, b = r.tasks
    assert (a.domain, a.origin, a.graph_id, a.target_state) == ("PD", "신규", "SLITM_APRVL_GBCD", None)
    assert [(c.name, c.value, c.role) for c in a.constraints] == [("가격", "50000원", "설정값"), ("상품 종류", "설치상품", "설정값")]
    assert (b.domain, b.target_state, b.depends_on) == ("OD", "배송완료", [1])


def test_rollback_keeps_must_pass(graphs):
    q = "배송완료된 주문 3건을 배송완료 취소시켜줘"
    r, _ = to_task_plan(plan(q, task(action="배송완료취소", target_state="출고", must_pass=["배송완료", "출고"], count=3,
                                     source_phrases=[q])), q, graphs)
    t = r.tasks[0]
    assert (t.target_state, t.must_pass, t.count) == ("출고", ["배송완료"], 3)       # target 과 같은 must_pass 는 뺀다


def test_no_graph_task(graphs):
    q = "협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘"
    t = task(domain="PD", action="브랜드코드변경", graph_id=None, target_state=None, source_phrases=[q],
             constraints=[{"name": "협력사코드", "value": "000000", "role": "대상조건", "source_phrase": "협력사코드가 000000인"},
                          {"name": "브랜드코드", "value": "1234", "role": "설정값", "source_phrase": "브랜드코드를 1234로"}])
    r, _ = to_task_plan(plan(q, t), q, graphs)
    assert r.tasks[0].graph_id is None and r.tasks[0].constraints[0].value == "000000"   # 코드값 앞자리 0 그대로
    with pytest.raises(GoalError, match="그래프 없이 상태"):
        to_task_plan(plan(q, {**t, "target_state": "출고"}), q, graphs)


@pytest.mark.parametrize("bad, msg", [
    (task(target_state="임시저장", source_phrases=[Q1]), "주문상태 그래프에 없는 상태"),             # 다른 그래프의 상태
    (task(must_pass=["승인완료"], source_phrases=[Q1]), "그래프에 없는 상태"),
    (task(source_phrases=["가격이 5만원인"]), "환각 의심"),                                          # 원문에 없는 근거
    (task(source_phrases=[Q1], constraints=[{"name": "가격", "value": "60000원", "role": "설정값",
                                              "source_phrase": "가격이 60000원인"}]), "환각 의심"),
    (task(source_phrases=[]), "근거 구절이 없습니다"),
    (task(source_phrases=[Q1], graph_id="NO_GRAPH"), "알 수 없는 그래프"),
])
def test_rejects(graphs, bad, msg):
    with pytest.raises(GoalError, match=msg):
        to_task_plan(plan(Q1, bad), Q1, graphs)


def test_rejects_bad_order(graphs):
    ok = task(source_phrases=[Q1])
    with pytest.raises(GoalError, match="빈틈없지"):
        to_task_plan(plan(Q1, ok, {**ok, "sequence": 3}), Q1, graphs)
    with pytest.raises(GoalError, match="앞 업무가 아닙니다"):
        to_task_plan(plan(Q1, {**ok, "depends_on": [2]}, {**ok, "sequence": 2}), Q1, graphs)


def test_fixes_domain_and_question(graphs):
    r, notes = to_task_plan(plan("다른 문장", task(domain="DS", source_phrases=["배송완료"])), "배송완료 처리", graphs)
    assert r.tasks[0].domain == "OD" and r.original_question == "배송완료 처리"
    assert any("DS → OD" in n for n in notes) and any("original_question" in n for n in notes)


def test_not_a_request(graphs):
    r, _ = to_task_plan(plan("주문상태 코드가 몇 개야?"), "주문상태 코드가 몇 개야?", graphs)
    assert r.tasks == [] and r.unresolved == []


def test_analyze_intent_reads_config(tmp_path):
    rules = tmp_path / "rules.ui.yaml"
    rules.write_text("rules:\n- {id: 1, doc: sv, item: syn, target: 'ORD_STAT_GBCD:45', body: 발송}\n", encoding="utf-8")
    seen = {}

    def llm(messages, schema):
        seen["sys"] = messages[0]["content"]
        return schema.model_validate(EX1)
    r = analyze_intent(Q1, [ROOT / "data/graphs"], rules_cfg=rules, llm=llm)
    assert len(r["plan"].tasks) == 2 and "출고(다른 표현: 발송)" in seen["sys"]


def test_no_graphs(domains):
    q = "상품 하나 만들어줘"
    S = task_schema(domains, [])
    out = S.model_validate(plan(q, task(domain="PD", graph_id=None, target_state=None, source_phrases=[q])))
    assert to_task_plan(out, q, [])[0].tasks[0].graph_id is None
