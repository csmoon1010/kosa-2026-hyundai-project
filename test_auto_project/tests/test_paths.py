"""그래프 경로 탐색 — 업무 목록 → 업무마다 그래프 · 출발 · 목표 상태 · 경로 (LLM 없이)."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tap.cli import analyze_paths
from tap.goal.extract import GoalError, TaskPlan
from tap.graph.build import graph_from_dict, load_graphs
from tap.graph.model import Require
from tap.graph.paths import build_paths, choice_schema, find_paths, graphs_text, path_messages, to_choices

ROOT = Path(__file__).resolve().parents[1]

# 새로 만들기 화살표 · 기본 완성 상태가 있는 시험용 상품 그래프 (공개 명세에는 상품 등록 · 승인 API 가 없다)
ITEM = {"graph": {"id": "TEST_ITEM", "name": "시험상품", "domain": "pd", "entity": "상품", "ready_state": "2"},
        "code_group": {"id": "TEST_ITEM", "name": "시험상품승인", "codes": {"0": "임시저장", "1": "팀장승인대기", "2": "승인완료"}},
        "transitions": [{"name": "상품 등록", "from": "시작", "to": "0", "api": "x:POST:/reg.do"},
                        {"name": "승인 요청", "from": "0", "to": "1", "api": "x:POST:/req.do"},
                        {"name": "팀장 승인", "from": "1", "to": "2", "api": "x:POST:/ok.do"}],
        "lookups": []}


@pytest.fixture()
def graphs():
    return load_graphs([ROOT / "data/graphs"])[0]


def G(graphs, gid):
    return next(g for g in graphs if g.graph_id == gid)


def task(seq=1, origin="기존", domain="OD", phrases=("주문",), depends=()):
    return {"sequence": seq, "domain": domain, "origin": origin, "action": "a", "conditions": "c", "constraints": [],
            "depends_on": list(depends), "count": 1, "source_phrases": list(phrases)}


def tp(q, *tasks):
    return TaskPlan.model_validate({"original_question": q, "tasks": list(tasks), "unresolved": []})


def choice(seq=1, graph="ORD_STAT_GBCD", frm=None, to=None, must=(), phrases=()):
    return {"sequence": seq, "graph_id": graph, "from_state": frm, "to_state": to, "must_pass": list(must),
            "state_phrases": list(phrases), "reason": "r"}


def run(plan_, graphs, *choices):
    ch, unresolved, notes = to_choices({"choices": list(choices), "unresolved": []}, plan_, graphs)
    return build_paths(plan_, ch, graphs), notes


def names(steps):
    return [(s.from_, s.to, s.edge) for s in steps]


def test_messages_and_schema(graphs):
    t = graphs_text(graphs + [graph_from_dict(ITEM)])
    assert "배송완료취소(배송완료→출고)" in t and "상품 등록(시작→임시저장)" in t and "동작: (아직 없음)" in t
    q = "배송완료된 주문 3건을 배송완료 취소시켜줘"
    m = path_messages(tp(q, task(phrases=[q])), graphs)[0]["content"]
    assert q in m and '"origin": "기존"' in m and "경로(어떤 화살표를 거칠지)와 API 는 고르지 않는다" in m
    S = choice_schema(graphs)
    S.model_validate({"choices": [choice(to="출고")], "unresolved": []})
    with pytest.raises(ValidationError):
        S.model_validate({"choices": [choice(to="구매확정")], "unresolved": []})


def test_existing_with_from_state_finds_it_directly(graphs):
    q = "배송완료된 주문 3건을 배송완료 취소시켜줘"
    pp, _ = run(tp(q, task(phrases=[q])), graphs, choice(frm="배송완료", to="출고", phrases=["배송완료된 주문", "배송완료 취소시켜줘"]))
    p = pp.paths[0]
    assert (p.status, p.from_state, p.start_by, p.to_state) == ("ok", "배송완료", "조회", "출고")
    assert names(p.steps) == [("배송완료", "출고", "배송완료취소")]
    assert p.to_state_reason == "요청: '배송완료된 주문' · '배송완료 취소시켜줘'"
    alt = p.alternatives[0]                                                              # 배송완료 주문이 없을 때 — 앞에서 진행
    assert alt.from_state == "출고대기" and [s.edge for s in alt.steps] == ["출고진행", "출고완료", "배송완료", "배송완료취소"]
    assert pp.dump()["paths"][0]["steps"][0]["from"] == "배송완료"                      # 출력 키는 'from'


def test_existing_without_from_state_advances(graphs):
    q = "출고된 주문 하나 줘"
    p = run(tp(q, task(phrases=[q])), graphs, choice(to="출고", phrases=["출고된 주문"]))[0].paths[0]
    assert (p.from_state, len(p.steps)) == ("출고대기", 2)                               # 기본: 찾을 수 있는 가장 앞 상태에서 진행
    assert p.alternatives[0].from_state == "출고" and p.alternatives[0].steps == []       # 대안: 출고 주문을 바로 찾기


def test_from_state_only_uses_that_data(graphs):
    q = "출고진행 중인 주문 하나 줘"
    p = run(tp(q, task(phrases=[q])), graphs, choice(frm="출고진행", to="출고진행", phrases=["출고진행 중인 주문"]))[0].paths[0]
    assert (p.from_state, p.to_state, p.steps) == ("출고진행", "출고진행", [])
    assert "그대로 씀" in p.to_state_reason
    q2 = "배송완료된 주문 하나를 구매확정 처리해줘"                                       # 목표가 비면 '그대로 씀'으로 채우지 않는다
    pp = run(tp(q2, task(phrases=[q2])), graphs, choice(frm="배송완료", phrases=["배송완료된"]))[0]
    assert pp.paths[0].status == "경로 없음" and "목표 상태를 정할 수 없습니다" in pp.unresolved[0]


def test_new_without_create_edge_falls_back_to_lookup(graphs):
    q = "출고된 주문 1건 만들어줘"
    p = run(tp(q, task(origin="신규", phrases=[q])), graphs, choice(to="출고", phrases=["출고된 주문"]))[0].paths[0]
    assert (p.origin, p.start_by, p.from_state, p.status) == ("신규", "조회", "출고대기", "ok")   # origin 과 start_by 가 다르다
    assert any("새로 만들 수 없어" in n for n in p.notes)                                # 숨기지 않는다


def test_new_with_create_edge_and_requires(graphs):
    """상품 신규(목표 말 안 함) → 주문 신규가 바라는 상태(승인완료)를 선행 조건으로 채운다."""
    item = graph_from_dict(ITEM)
    ord_ = G(graphs, "ORD_STAT_GBCD").model_copy(deep=True)
    ord_.requires = [Require(graph_id="TEST_ITEM", state="2", when="신규")]
    q = "설치상품을 만들고 주문한 뒤 배송완료까지 처리해줘"
    plan_ = tp(q, task(1, "신규", "PD", ["설치상품을 만들고"]), task(2, "신규", "OD", ["주문한 뒤 배송완료까지 처리해줘"], [1]))
    pp, _ = run(plan_, [item, ord_], choice(1, "TEST_ITEM"), choice(2, to="배송완료", phrases=["배송완료까지"]))
    a, b = pp.paths
    assert (a.from_state, a.start_by, a.to_state) == ("시작", "새로 만들기", "승인완료")
    assert a.to_state_reason.startswith("선행 조건: 2번 업무(주문상태 신규)")
    assert names(a.steps) == [("시작", "임시저장", "상품 등록"), ("임시저장", "팀장승인대기", "승인 요청"), ("팀장승인대기", "승인완료", "팀장 승인")]
    assert (b.start_by, b.to_state, b.depends_on) == ("조회", "배송완료", [1])            # 주문은 새로 만들기 화살표가 없어 조회로
    ord_.requires = []
    a2 = run(plan_, [item, ord_], choice(1, "TEST_ITEM"), choice(2, to="배송완료"))[0].paths[0]
    assert (a2.to_state, a2.to_state_reason) == ("승인완료", "기본 완성 상태 (시험상품 그래프에 적힌 값)")


def test_no_target_and_no_path(graphs):
    q = "상품 하나 만들어줘"
    pp = run(tp(q, task(origin="신규", domain="PD", phrases=[q])), graphs, choice(graph="SLITM_APRVL_GBCD"))[0]
    assert pp.paths[0].status == "경로 없음" and "목표 상태를 정할 수 없습니다" in pp.unresolved[0]
    q2 = "승인완료된 상품 하나 만들어줘"
    pp2 = run(tp(q2, task(origin="신규", domain="PD", phrases=[q2])), graphs,
              choice(graph="SLITM_APRVL_GBCD", to="승인완료", phrases=["승인완료된 상품"]))[0]
    p = pp2.paths[0]
    assert (p.status, p.to_state, p.from_state) == ("경로 없음", "승인완료", "시작") and "새로 만들기 화살표가 없고" in pp2.unresolved[0]


def test_no_graph_task_and_domain_fix(graphs):
    q = "배송완료 처리하고 브랜드코드를 1234로 바꿔줘"
    plan_ = tp(q, task(1, domain="DS", phrases=["배송완료 처리"]), task(2, domain="PD", phrases=["브랜드코드를 1234로"]))
    pp, _ = run(plan_, graphs, choice(1, to="배송완료", phrases=["배송완료"]), choice(2, graph=None))
    a, b = pp.paths
    assert a.domain == "OD" and any("DS → OD" in n for n in a.notes)
    assert (b.status, b.graph_id, b.steps, b.domain) == ("그래프 없음", None, [], "PD")


@pytest.mark.parametrize("bad, msg", [
    (choice(to="임시저장"), "주문상태 그래프에 없는 상태"),
    (choice(graph=None, to="출고"), "그래프 없이 상태"),
    (choice(to="출고", phrases=["발송된 주문"]), "환각 의심"),
    (choice(seq=2, to="출고"), "업무마다 하나씩"),
])
def test_choice_checks(graphs, bad, msg):
    with pytest.raises(GoalError, match=msg):
        to_choices({"choices": [bad], "unresolved": []}, tp("출고된 주문", task(phrases=["출고된 주문"])), graphs)


def test_new_task_drops_from_state(graphs):
    q = "출고된 주문 만들어줘"
    ch, _, notes = to_choices({"choices": [choice(frm="출고대기", to="출고")], "unresolved": []},
                              tp(q, task(origin="신규", phrases=[q])), graphs)
    assert ch[1]["from"] is None and "신규라 출발 상태" in notes[0]


def test_find_paths_and_analyze_paths(graphs):
    called = []
    pp, _ = find_paths(tp("주문상태 코드가 몇 개야?"), graphs, lambda m, s: called.append(1))
    assert pp.paths == [] and called == []                                               # 업무가 없으면 LLM 을 부르지 않는다
    q = "배송완료된 주문 하나를 배송완료 취소해줘"

    def llm(messages, schema):                                                           # 업무 의도 분석 → 경로 탐색 차례로
        if schema.__name__ == "TaskPlanOut":
            return schema.model_validate({"original_question": q, "tasks": [task(phrases=[q])], "unresolved": []})
        return schema.model_validate({"choices": [choice(frm="배송완료", to="출고", phrases=["배송완료된 주문"])], "unresolved": []})
    r = analyze_paths(q, llm=llm)
    assert r["paths"].paths[0].steps[0].edge == "배송완료취소"
    tasks_json = json.dumps({"original_question": q, "tasks": [task(phrases=[q])], "unresolved": []}, ensure_ascii=False)
    r2 = analyze_paths(q, llm=llm, tasks_json=tasks_json)                                # 업무 목록을 주면 의도 분석을 건너뜀
    assert r2["paths"].paths[0].from_state == "배송완료"


def test_state_must_come_from_request_words(graphs):
    """LLM 이 그래프에 없는 말을 비슷한 상태로 바꾸면(구매확정 → 완료) 버리고 unresolved 로."""
    q = "배송완료된 주문 하나를 구매확정 처리해줘"
    ch, unresolved, _ = to_choices({"choices": [choice(frm="배송완료", to="완료", phrases=["배송완료된"])], "unresolved": []},
                                   tp(q, task(phrases=[q])), graphs)
    assert ch[1]["to"] is None and ch[1]["from"] == "50" and "'완료'는 요청의 말" in unresolved[0]   # '배송완료' 안의 '완료' 는 안 셈
    q2 = "배송완료된 주문을 배송완료 취소시켜줘"                                            # 동작 이름(띄어 써도) → 도착 상태 출고
    ch2, u2, _ = to_choices({"choices": [choice(frm="배송완료", to="출고")], "unresolved": []}, tp(q2, task(phrases=[q2])), graphs)
    assert (ch2[1]["from"], ch2[1]["to"], u2) == ("50", "45", [])
    g = G(graphs, "ORD_STAT_GBCD").model_copy(deep=True)
    g.node("45").synonyms = ["발송"]                                                     # State Vocabulary 다른 표현
    ch3, u3, _ = to_choices({"choices": [choice(to="출고")], "unresolved": []}, tp("발송된 주문 줘", task(phrases=["발송된 주문"])), [g])
    assert ch3[1]["to"] == "45" and u3 == []


def test_dependency_failure_noted(graphs):
    q = "상품을 만들고 주문해서 출고까지"
    plan_ = tp(q, task(1, "신규", "PD", ["상품을 만들고"]), task(2, "신규", "OD", ["주문해서 출고까지"], [1]))
    pp, _ = run(plan_, graphs, choice(1, "SLITM_APRVL_GBCD"), choice(2, to="출고", phrases=["출고까지"]))
    a, b = pp.paths
    assert a.status == "경로 없음" and a.notes == []                                      # 조회로도 못 하면 '조회로 만듭니다' 안내 없음
    assert b.status == "ok" and any("앞 업무 [1]번이 경로 없음" in n for n in b.notes)



def test_existing_task_with_graph_but_no_state_is_graphless(graphs):
    """기존 업무에 그래프만 고르고 상태는 하나도 안 골랐으면 그래프 없음 — 실행마다 길이 갈리지 않게 (브랜드코드 변경)."""
    q = "협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘"
    plan_ = tp(q, task(domain="PD", phrases=[q]))
    ch, _, notes = to_choices({"choices": [choice(graph="SLITM_APRVL_GBCD")], "unresolved": []}, plan_, graphs)
    assert ch[1]["graph_id"] is None and "상태를 하나도 고르지 않아" in notes[0]
    assert build_paths(plan_, ch, graphs).paths[0].status == "그래프 없음"
    q2 = "발송된 주문 하나 줘"                                                           # 고른 상태를 코드가 버린 경우는 그대로 (경로 없음)
    ch2, u2, _ = to_choices({"choices": [choice(to="출고")], "unresolved": []}, tp(q2, task(phrases=[q2])), graphs)
    assert ch2[1]["graph_id"] == "ORD_STAT_GBCD" and ch2[1]["to"] is None
    ch3, _, n3 = to_choices({"choices": [choice(graph="SLITM_APRVL_GBCD")], "unresolved": []},
                            tp("상품 하나 만들어줘", task(origin="신규", domain="PD", phrases=["상품"])), graphs)
    assert ch3[1]["graph_id"] == "SLITM_APRVL_GBCD" and n3 == []                          # 신규는 목표를 코드가 채울 수 있어 그대로
