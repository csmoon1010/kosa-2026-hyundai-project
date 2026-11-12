"""정답 그래프로 — 그래프 모양 · 검증 · 경로 계산(graph/plan.py, ② 경로 탐색이 쓴다). LLM 없이."""
import json
from pathlib import Path

import pytest

from tap.cli import build
from tap.graph.build import load_knowledge, validate_graph
from tap.graph.plan import Goal, plan

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
