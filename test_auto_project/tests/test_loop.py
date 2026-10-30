"""작은 그래프로 한 바퀴 — 그래프 · 경로 계산 · 목표 검증 · Scenario IR (LLM 없이)."""
import json
from pathlib import Path

import pytest

from tap.cli import build, plan_request
from tap.goal.extract import GoalError, build_messages, extract_goal, goal_schema, to_goal
from tap.graph.build import load_knowledge, validate_graph
from tap.graph.plan import Goal, plan
from tap.ir.build import build_ir

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "data/golden/ORD_STAT_GBCD.yaml"
G = "ORD_STAT_GBCD"


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("out")
    build(ROOT / "data/specs/hmall-openapi.json", d, ROOT / "data/config/domains.yaml",
          ROOT / "data/config/services.yaml", ROOT / "data/config/overrides.yaml", now="2026-10-25T10:00:00+09:00")
    return d


@pytest.fixture(scope="module")
def graph():
    return load_knowledge(KNOW)


def j(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 그래프

def test_graph_shape(graph):
    assert graph.entry_states == ["25"] and graph.state_field == "lastDlvstPrgrGbcd"
    assert [graph.node(c).stage for c in ("25", "30", "45", "50")] == [0, 1, 2, 3]
    rev = {e.name for e in graph.edges if e.reverse}
    assert rev == {"출고취소", "출고완료취소", "배송완료취소"}                  # 단계가 거꾸로 가는 간선
    p1 = next(e for e in graph.edges if e.name == "출고진행")
    assert (p1.api_id.endswith("multiOshpProcess.do"), p1.selector) == (True, {"procGb": "P1"})


def test_graph_validation(graph, out):
    issues = validate_graph(graph, j(out / "api_metadata.json"), j(out / "api_operations.json"))
    assert not [i for i in issues if i["level"] == "error"]
    assert any("56" in i["message"] for i in issues if i["level"] == "warn")   # 코드 목록에 없는 56


def test_validation_catches_bad_selector(graph, out):
    bad = graph.model_copy(deep=True)
    bad.edges[0].selector = {"noSuchField": "X"}
    issues = validate_graph(bad, j(out / "api_metadata.json"), j(out / "api_operations.json"))
    assert any("선택값 필드 noSuchField" in i["message"] for i in issues if i["level"] == "error")


# ------------------------------------------------------------------ 경로 계산

@pytest.mark.parametrize("goal, a_states, b_start, b_writes", [
    (dict(target="45"), ["25", "30", "45"], "45", 0),                         # 출고된 주문
    (dict(target="45", must_pass=["50"]), ["25", "30", "45", "50", "45"], "50", 1),   # 배송완료 후 취소
    (dict(target="50", count=2), ["25", "30", "45", "50"], "50", 0),          # 배송완료 2건
])
def test_plan_advance_default_lookup_alternative(graph, goal, a_states, b_start, b_writes):
    r = plan(graph, Goal(graph_id=G, **goal))
    assert r.status == "ok"
    assert (r.primary.strategy, r.primary.start, r.primary.states) == ("advance", "25", a_states)
    assert (r.alternative.strategy, r.alternative.start, r.alternative.writes) == ("lookup", b_start, b_writes)


def test_plan_rejects_external_state(graph):
    r = plan(graph, Goal(graph_id=G, target="20"))                              # 결제완료
    assert r.status == "rejected" and "API 로 만들 수 없는 상태" in r.reason and "조회로 찾는 방법도" in r.reason


def test_plan_same_goal_same_path(graph):
    g = Goal(graph_id=G, target="50")
    assert [e.id for e in plan(graph, g).primary.edges] == [e.id for e in plan(graph, g).primary.edges]


# ------------------------------------------------------------------ 목표 검증 (가짜 LLM)

def fake_llm(payload):
    def parse(messages, schema):
        return schema(**payload)
    return parse


def test_extract_goal_with_fake_llm(graph):
    u = "배송완료된 주문 1건을 배송완료 취소시켜줘."
    goal = extract_goal(u, graph, fake_llm({"target": "출고", "must_pass": ["배송완료"], "count": 1,
                                            "source_phrases": ["배송완료된 주문", "배송완료 취소"]}))
    assert (goal.target, goal.must_pass, goal.count) == ("45", ["50"], 1)


def test_goal_rejects_hallucinated_phrase(graph):
    with pytest.raises(GoalError, match="원문에 없습니다"):
        to_goal({"target": "출고", "source_phrases": ["브랜드 AAA"]}, "출고된 주문 1건", graph)


def test_goal_schema_limits_states(graph):
    schema = goal_schema(graph)
    with pytest.raises(Exception):
        schema(target="없는상태", source_phrases=["x"])                       # 상태 목록 밖은 못 고른다
    assert "출고대기 (25)" in build_messages("x", graph)[0]["content"]


# ------------------------------------------------------------------ Scenario IR

def test_ir_steps(graph, out):
    goal = Goal(graph_id=G, target="45", count=1)
    ir = build_ir("출고된 주문 1건", goal, graph, plan(graph, goal),
                  j(out / "api_operations.json"), j(out / "api_metadata.json"), 1)
    kinds = [s.kind for s in ir.steps]
    assert kinds == ["lookup", "call", "call", "verify"]
    lk, p1, p2, vf = ir.steps
    assert lk.params["prgrGb"].value == "P0" and lk.pick == 1                  # 출고대기만 서버가 걸러 줌
    assert p1.params["procGb"].source == "fixed" and p1.params["procGb"].value == "P1"
    assert p1.params["ordNo"].ref == "step1.ordNo"                             # 앞 호출 응답 → 같은 이름
    assert p1.compensate_with.endswith(":PB1") and p2.compensate_with.endswith(":PB2")
    assert vf.params["prgrGb"].value == "P2" and vf.expect_state == "45"
    assert ir.requires_approval and "venCd" in ir.run_inputs
    assert ir.alternative.strategy == "lookup" and ir.alternative.writes == 0


def test_plan_request_end_to_end_without_llm(out):
    goal = Goal(graph_id=G, target="20").model_dump_json()
    r = plan_request("결제완료 상태 주문 만들어줘.", KNOW, out, goal_json=goal)
    saved = j(r["file"])
    assert saved["status"] == "rejected" and saved["steps"] == []


def test_plan_without_entry_states_same_results():
    """진입 상태를 정하지 않아도 (화면에서 만든 그래프) 찾을 수 있는 상태 중 정렬순서가 가장 앞인 곳에서 출발한다."""
    import yaml
    from tap.graph.build import graph_from_dict
    k = yaml.safe_load(KNOW.read_text(encoding="utf-8")); k["graph"]["entry_states"] = []
    g = graph_from_dict(k)
    assert plan(g, Goal(graph_id=G, target="45", must_pass=["50"])).primary.states == ["25", "30", "45", "50", "45"]
    r = plan(g, Goal(graph_id=G, target="25"))
    assert (r.primary.start, r.primary.writes, r.alternative) == ("25", 0, None)       # 출고대기는 바로 찾기 — 취소를 거꾸로 돌지 않는다
    assert plan(g, Goal(graph_id=G, target="20")).status == "rejected"
