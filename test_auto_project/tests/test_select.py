"""API 선택 — 경로의 단계마다 API (+ 구분값). 그래프 고정 · 규칙 · LLM(가짜) · 보류 (LLM 없이)."""
import copy
import json
from pathlib import Path

import pytest

from tap.apis.select import check, select_apis
from tap.cli import analyze_select
from tap.goal.extract import TaskPlan
from tap.graph.build import load_graphs
from tap.graph.match import Candidate
from tap.graph.paths import build_paths, to_choices

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / "data/out/api_metadata.json").read_text(encoding="utf-8"))
OPS = json.loads((ROOT / "data/out/api_operations.json").read_text(encoding="utf-8"))
CAT = json.loads((ROOT / "data/out/api_catalog.json").read_text(encoding="utf-8"))
BACK = "hshop-openapi:POST:/sc/scb/scbd/multiOshpBackProcess.do"
GO = "hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do"
LOOK = "hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do"


@pytest.fixture()
def graphs():
    from tap.graph.match import attach_lookups
    gs = load_graphs([ROOT / "data/graphs"], keep_unmatched=True)[0]
    attach_lookups(gs, META, OPS, ["pd", "od", "ds"])                                  # 노드 흐름만인 그래프 — 경로 탐색 때 조회를 붙인다
    return gs


def ord_of(graphs):
    return next(g for g in graphs if g.graph_id == "ORD_STAT_GBCD")


def unpinned(graphs):
    return ord_of(graphs)


def task(seq=1, origin="기존", domain="OD", phrases=("주문",), constraints=(), action="a"):
    return {"sequence": seq, "domain": domain, "origin": origin, "action": action, "conditions": "c",
            "constraints": list(constraints), "depends_on": [], "count": 1, "source_phrases": list(phrases)}


def choice(seq=1, graph="ORD_STAT_GBCD", frm=None, to=None):
    return {"sequence": seq, "graph_id": graph, "from_state": frm, "to_state": to, "must_pass": [], "state_phrases": [], "reason": "r"}


def paths(q, graphs, tasks, choices):
    tp = TaskPlan.model_validate({"original_question": q, "tasks": tasks, "unresolved": []})
    ch, _, _ = to_choices({"choices": choices, "unresolved": []}, tp, graphs)
    return tp, build_paths(tp, ch, graphs)


def no_llm(messages, schema):
    raise AssertionError("LLM 을 부르면 안 됨")


Q = "배송완료된 주문 3건을 배송완료 취소시켜줘"


def test_rule_picks_apis_from_metadata(graphs):
    """그래프에는 API 가 없다 — 카탈로그 · 메타데이터에서 규칙으로 고른다 (구분값까지)."""
    tp, pp = paths(Q, graphs, [task(phrases=[Q])], [choice(frm="배송완료", to="출고")])
    r = select_apis(tp, pp, graphs, META, OPS, CAT, no_llm)
    a, b = r.api_selection_results
    assert (a.step, a.kind, a.edge, a.to) == (0, "조회", "배송완료 데이터 찾기", "배송완료")
    assert (a.selected.api_id, a.selected.selector, a.selection_status, a.selected_by) == (LOOK, {"prgrGb": "P3"}, "선택", "규칙")
    assert (b.step, b.kind, b.from_, b.to) == (1, "상태변경", "배송완료", "출고")
    assert (b.selected.api_id, b.selected.selector, b.selection_status, b.selected_by) == (BACK, {"procGb": "PB3"}, "선택", "규칙")
    assert b.api_candidates[0].check == "통과" and len(b.api_candidates) > 1                        # 후보 · 검사 결과도 남긴다
    assert r.status == "완료" and r.dump()["api_selection_results"][1]["from"] == "배송완료"


def test_ambiguous_goes_to_llm(graphs):
    """같은 동작을 하는 API 가 둘이면 규칙이 못 고른다 → LLM 이 후보 안에서."""
    g = unpinned(graphs)
    twin = copy.deepcopy(next(m for m in META if m["api_id"] == BACK))
    twin["api_id"] = twin["api_id"].replace("multiOshpBackProcess", "multiOshpBackProcess2")
    op = copy.deepcopy(next(o for o in OPS if o["api_id"] == BACK))
    op["api_id"] = twin["api_id"]
    tp, pp = paths(Q, [g], [task(phrases=[Q])], [choice(frm="배송완료", to="출고")])
    seen = {}

    def llm(messages, schema):
        seen["sys"] = messages[0]["content"]
        return schema.model_validate({"picks": [{"key": "1-1", "choice": "B", "reason": "명세 설명", "concerns": ["설치상품 확인"]}]})
    r = select_apis(tp, pp, [g], META + [twin], OPS + [op], None, llm)
    b = r.api_selection_results[1]
    assert "key 1-1" in seen["sys"] and "A) 출고취소처리" in seen["sys"] and "B) 출고취소처리" in seen["sys"]
    assert (b.selected_by, b.selection_status) == ("LLM", "가선택") and "설치상품 확인" in b.selection_reason
    assert r.status == "검토 필요" and any(u.reason == "설치상품 확인" for u in r.unresolved)

    def none(messages, schema):
        return schema.model_validate({"picks": [{"key": "1-1", "choice": "없음", "reason": "둘 다 아님", "concerns": []}]})
    r2 = select_apis(tp, pp, [g], META + [twin], OPS + [op], None, none)
    assert r2.api_selection_results[1].selection_status == "보류" and r2.status == "보류"


def test_metadata_check():
    meta = {m["api_id"]: m for m in META}
    req = {o["api_id"]: {f["name"] for f in o["request_fields"]} for o in OPS}
    c = lambda api, sel: Candidate(api_id=api, api_name="x", selector=sel, score=1)
    assert check(c(BACK, {"procGb": "PB3"}), "상태변경", meta, req, None) == ("통과", None)
    assert check(c(BACK, {"procGb": "PB3"}), "조회", meta, req, None)[0] == "탈락"                    # 종류가 다름
    assert "구분값 목록에 없음" in check(c(BACK, {"procGb": "PB9"}), "상태변경", meta, req, None)[1]    # 목록이 완성돼 있으면 탈락
    assert check(c(BACK, {"nope": "1"}), "상태변경", meta, req, None)[1] == "구분값 필드 nope 가 요청에 없음"
    assert "값을 모름" in check(c(BACK, {"procGb": "?"}), "상태변경", meta, req, None)[1]
    m2 = {**meta, BACK: {**meta[BACK], "irreversible": "불가"}}
    assert check(c(BACK, {"procGb": "PB3"}), "상태변경", m2, req, None)[0] == "주의"


def test_catalog_limits_candidates(graphs):
    g = unpinned(graphs)
    cat = copy.deepcopy(CAT)
    for a in cat["apis"]:
        if a["api_id"] == BACK:
            a["tool_enabled"] = False                                                                # 카탈로그에서 사용 안 함
    tp, pp = paths(Q, [g], [task(phrases=[Q])], [choice(frm="배송완료", to="출고")])
    b = select_apis(tp, pp, [g], META, OPS, cat, no_llm).api_selection_results[1]
    assert all(c.api_id != BACK for c in b.api_candidates)


def test_no_graph_task_is_always_tentative(graphs):
    q = "협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘"
    cons = [{"name": "협력사코드", "value": "000000", "role": "대상조건", "source_phrase": "협력사코드가 000000인"},
            {"name": "브랜드코드", "value": "1234", "role": "설정값", "source_phrase": "브랜드코드를 1234로"}]
    tp, pp = paths(q, graphs, [task(domain="PD", phrases=[q], constraints=cons, action="브랜드코드변경")], [choice(graph=None)])

    def llm(messages, schema):
        keys = schema.model_fields["picks"].annotation.__args__[0].model_fields["key"].annotation.__args__
        return schema.model_validate({"picks": [{"key": k, "choice": "A", "reason": "필드", "concerns": []} for k in keys]})
    r = select_apis(tp, pp, graphs, META, OPS, CAT, llm)
    kinds = [(x.step, x.kind) for x in r.api_selection_results]
    assert kinds == [(0, "조회"), (1, "수정")]
    assert all(x.selection_status in ("가선택", "보류") for x in r.api_selection_results) and r.status != "완료"


def test_new_task_without_graph_creates(graphs):
    """그래프 없는 신규 업무 — 대상 찾기 없이 '생성' 하나, 새로 만드는 API(상품 등록)를 고른다. 사람 확인 · 되돌릴 수 없음 (2026-11-06)."""
    from tap.apis.gate import gate_for, load_permissions
    q = "주문제작 상품을 2개 생성해줘"
    cons = [{"name": "상품 종류", "value": "주문제작 상품", "role": "설정값", "source_phrase": "주문제작 상품"}]
    tp, pp = paths(q, graphs, [task(origin="신규", domain="PD", phrases=[q], constraints=cons, action="상품생성")],
                   [choice(graph="SLITM_APRVL_GBCD")])                 # 새로 만들기 화살표 없는 그래프 → ② 가 그래프 없음으로
    r = select_apis(tp, pp, graphs, META, OPS, CAT, no_llm)
    [x] = r.api_selection_results
    assert (x.step, x.kind, x.selected.api_id.rsplit("/", 1)[-1], x.selection_status) == (1, "생성", "multiItem.do", "가선택")
    assert x.api_candidates[0].score - x.api_candidates[1].score >= 0.15 and "새로 등록하는 API" in x.selection_reason
    g = gate_for(r, pp, graphs, META, load_permissions(ROOT / "data/config/permissions.yaml"))
    assert [(s.tier, s.requirement) for s in g.steps] == [("R2", "단계 승인")] and g.status == "승인 필요"


def test_reference_lookups_before_write(graphs, tmp_path):
    """설정값이 이름("아디다스")이고 고른 쓰기 API 에 그 코드 필드가 있으면 — 이름으로 코드를 찾는 조회를 앞 단계로 (2026-11-11)."""
    from tap.apis.gate import approve, gate_for, load_permissions
    from tap.ir.draft_build import fixed_plan
    from tap.ir.handoff import hyejung_approved
    q = '"아디다스" 브랜드코드와 "아디다스" 제조사코드를 조회하고 조회한 코드들로 상품을 1개 생성해줘'
    cons = [{"name": "브랜드코드", "value": '"아디다스"', "role": "설정값", "source_phrase": '"아디다스" 브랜드코드'},
            {"name": "제조사", "value": "아디다스", "role": "대상조건", "source_phrase": '"아디다스" 제조사코드'}]   # 신규라 대상조건도 넣을 값
    tp, pp = paths(q, graphs, [task(origin="신규", domain="PD", phrases=[q], constraints=cons, action="상품생성")],
                   [choice(graph="SLITM_APRVL_GBCD")])
    r = select_apis(tp, pp, graphs, META, OPS, CAT, no_llm)
    got = [(x.step, x.kind, x.selected.api_id.rsplit("/", 1)[-1], x.selection_status) for x in r.api_selection_results]
    assert got == [(1, "조회", "selectBrndList.do", "선택"), (2, "조회", "selectMkcoList.do", "선택"), (3, "생성", "multiItem.do", "가선택")]
    a, b, _ = r.api_selection_results
    assert (a.reference.value, a.reference.name_field, a.reference.code_field, a.reference.for_step) == ("아디다스", "brndNm", "brndCd", 3)
    assert (b.reference.name_field, b.reference.output_field) == ("edtMkcoName", "mkcoCd")
    g = gate_for(r, pp, graphs, META, load_permissions(ROOT / "data/config/permissions.yaml"))
    assert [(s.key, s.tier) for s in g.steps] == [("1-1", "R0"), ("1-2", "R0"), ("1-3", "R2")]
    data = hyejung_approved(tp, pp, r, g, approve(g, "t", True, list(g.need_steps)))
    plan = fixed_plan(json.loads(json.dumps(data)))
    assert [(d["source_step_id"], d["input_field"]) for d in plan[2]["input_dependencies"]] == [("1-1", "brndCd"), ("1-2", "mkcoCd")]
    assert data["api_selection_results"][0]["reference"]["for_step_id"] == "1-3"


def test_reference_skipped_for_code_values(graphs):
    """값이 코드("1234")거나 쓰기 API 에 코드 필드가 없는 설정값(가격)은 참조 조회를 만들지 않는다."""
    from tap.apis.select import looks_like_name
    assert [looks_like_name(v) for v in ('"아디다스"', "Nike", "1234", "B001")] == [True, True, False, False]
    q = "브랜드코드 1234, 가격 오천원인 상품을 1개 생성해줘"
    cons = [{"name": "브랜드코드", "value": "1234", "role": "설정값", "source_phrase": "브랜드코드 1234"},
            {"name": "가격", "value": "오천원", "role": "설정값", "source_phrase": "가격 오천원"}]
    tp, pp = paths(q, graphs, [task(origin="신규", domain="PD", phrases=[q], constraints=cons, action="상품생성")],
                   [choice(graph="SLITM_APRVL_GBCD")])
    r = select_apis(tp, pp, graphs, META, OPS, CAT, no_llm)
    assert [(x.step, x.kind) for x in r.api_selection_results] == [(1, "생성")]


def test_no_path_and_alternative_hint(graphs):
    q = "승인완료된 상품 하나 만들어줘"            # 승인완료로 만들 길이 없음 → 경로 없음 → 업무 보류
    tp, pp = paths(q, graphs, [task(origin="신규", domain="PD", phrases=[q])], [choice(graph="SLITM_APRVL_GBCD", to="승인완료")])
    r = select_apis(tp, pp, graphs, META, OPS, CAT, no_llm)
    assert r.status == "보류" and r.api_selection_results == [] and {u.path_sequence for u in r.unresolved} == {1}
    g = ord_of(graphs).model_copy(deep=True)                                                         # 출고완료 화살표의 API 를 못 찾는 그래프
    e = next(x for x in g.edges if x.name == "출고완료")
    e.name, e.api_id, e.selector = "아무 이름", None, {}
    q2 = "출고된 주문 하나 줘"
    tp2, pp2 = paths(q2, [g], [task(phrases=[q2])], [choice(to="출고")])
    r2 = select_apis(tp2, pp2, [g], META, OPS, CAT, no_llm)
    held = [x for x in r2.api_selection_results if x.selection_status == "보류"]
    assert [x.edge for x in held] == ["아무 이름"] and r2.status == "보류"
    assert any("대안 경로(출고에서 조회" in u.reason for u in r2.unresolved)                         # 출고 주문을 바로 찾는 대안


def test_analyze_select_end_to_end(tmp_path):
    def llm(messages, schema):
        if schema.__name__ == "TaskPlanOut":
            return schema.model_validate({"original_question": Q, "tasks": [task(phrases=[Q])], "unresolved": []})
        if schema.__name__ == "PathChoiceOut":
            return schema.model_validate({"choices": [{**choice(frm="배송완료", to="출고"), "state_phrases": ["배송완료된 주문"]}],
                                          "unresolved": []})
        raise AssertionError("규칙으로 다 골라져 API 고르기 LLM 은 안 부름")
    r = analyze_select(Q, llm=llm, trace_dir=tmp_path)
    assert r["apis"].status == "완료" and [x.selected.selector for x in r["apis"].api_selection_results] == [{"prgrGb": "P3"}, {"procGb": "PB3"}]


def test_llm_sees_matching_fields_first():
    """필드가 많은 API 도 업무 용어와 맞는 필드를 LLM 에 먼저 보여 준다 — 앞에서 자르면 brndCd(119번째)가 빠진다."""
    from tap.apis.select import FIELDS_SHOWN, _show_fields
    ops = {o["operation_id"]: o for o in json.loads((ROOT / "data/out/api_operations.json").read_text(encoding="utf-8"))}
    fields = ops["multiItem"]["request_fields"]
    shown = _show_fields(fields, ["협력사코드", "브랜드코드"])
    assert shown.startswith("venCd(협력사코드) ← 협력사코드, brndCd(브랜드코드) ← 브랜드코드, ")
    assert shown.count("(") == FIELDS_SHOWN and "… 외 " in shown
    assert "← " not in _show_fields(fields, [])
