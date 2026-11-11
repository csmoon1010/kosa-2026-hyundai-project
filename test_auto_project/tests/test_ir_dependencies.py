"""혜정 ir/dependencies.py — 같은 업무 안 앞 단계 → 뒤 단계 의존 (2026-11-05 병합 때 추가). 업무 사이 의존은 그대로."""
import pytest

from tap.ir.dependencies import attach_dependencies

API = "hshop-openapi:POST:/sc/scb/scbd/"


def row(seq, step, edge, api, **extra):
    return {"path_sequence": seq, "step": step, "step_id": f"{seq}-{step}", "edge": edge, "selected_api_id": API + api, **extra}


def task(seq, conditions, action="a"):
    return {"sequence": seq, "domain": "OD", "action": action, "conditions": conditions, "count": 1}


def test_row_source_step_same_task():
    plan = [row(1, 1, "출고대기 데이터 찾기", "selectOshpDtlList.do"),
            row(1, 2, "출고진행", "multiOshpProcess.do", source_step_id="1-1"),
            row(1, 3, "출고완료", "multiOshpProcess.do", source_step_id="1-1", source_output_names=["ordNo"])]
    out = attach_dependencies(plan, [task(1, "001442 협력사의 주문을 조회해 배송완료 상태로 만든다.")])
    assert out[0]["input_dependencies"] == [] and [d["dependency_id"] for d in out[0]["output_consumers"]] == ["D-1-1-to-1-2", "D-1-1-to-1-3"]
    d2, d3 = out[1]["input_dependencies"][0], out[2]["input_dependencies"][0]
    assert (d2["source_step_id"], d2["status"], d2["consumer_task_sequence"]) == ("1-1", "resolved", 1)
    assert d3["source_output_names"] == ["ordNo"] and out[1]["output_consumers"] == []


def test_row_source_must_be_earlier():
    plan = [row(1, 1, "조회", "selectOshpDtlList.do", source_step_id="1-2"), row(1, 2, "출고진행", "multiOshpProcess.do")]
    with pytest.raises(ValueError, match="앞 단계가 아닙니다"):
        attach_dependencies(plan, [task(1, "c")])


def test_condition_record_same_task_attaches_only_after_source():
    plan = [row(1, 1, "주문 조회", "selectOshpDtlList.do"), row(1, 2, "출고진행", "multiOshpProcess.do"),
            row(1, 3, "출고완료", "multiOshpProcess.do")]
    out = attach_dependencies(plan, [task(1, [{"text": "조회한 주문 처리", "source_step_id": "1-1"}])])
    assert out[0]["input_dependencies"] == [] and [d["dependency_id"] for d in out[0]["output_consumers"]] == ["D-1-1-to-1"]   # 자기 자신에 의존하지 않음
    assert all(s["input_dependencies"][0]["source_step_id"] == "1-1" for s in out[1:])


def test_cross_task_dependency_unchanged():
    plan = [row(1, 1, "주문 조회", "selectOshpDtlList.do"), row(2, 1, "주문 확인 및 출고 진행", "multiOshpProcess.do"),
            row(2, 2, "출고 완료", "multiOshpProcess.do")]
    out = attach_dependencies(plan, [task(1, "협력사 코드 001442에 해당하는 주문을 조회한다."),
                                     task(2, "1번 업무에서 조회한 주문을 배송완료 상태까지 처리한다.")])
    assert [d["dependency_id"] for d in out[1]["input_dependencies"]] == ["D-1-to-2"] == [d["dependency_id"] for d in out[2]["input_dependencies"]]
    assert [d["consumer_task_sequence"] for d in out[0]["output_consumers"]] == [2]           # 업무 하나당 기록 하나 (원래 동작)


def test_reference_sources_one_dependency_each():
    """참조 조회 단계 여럿 → 쓰기 단계 하나 (2026-11-11). 출처마다 관계 하나, 꺼낼 출력 · 넣을 입력을 함께."""
    pd = "hshop-openapi:POST:/pd/"
    plan = [{**row(1, 1, "브랜드코드 찾기", "x"), "selected_api_id": pd + "pdh/selectBrndList.do"},
            {**row(1, 2, "제조사코드 찾기", "x"), "selected_api_id": pd + "pdh/selectMkcoList.do"},
            {**row(1, 3, "상품생성", "x"), "selected_api_id": pd + "pdb/multiItem.do", "reference_sources": [
                {"source_step_id": "1-1", "source_output_names": ["brndCd"], "input_field": "brndCd"},
                {"source_step_id": "1-2", "source_output_names": ["mkcoCd"], "input_field": "mkcoCd"}]}]
    out = attach_dependencies(plan, [task(1, "조회한 브랜드코드와 제조사코드로 상품을 만든다.", "상품생성")])
    deps = out[2]["input_dependencies"]
    assert [(d["source_step_id"], d["source_output_names"], d["input_field"], d["status"]) for d in deps] == [
        ("1-1", ["brndCd"], "brndCd", "resolved"), ("1-2", ["mkcoCd"], "mkcoCd", "resolved")]
    assert deps[1]["source_pointer"] == "/api_selection_results/2/reference_sources/1/source_step_id"
    assert [d["dependency_id"] for d in out[0]["output_consumers"]] == ["D-1-1-to-1-3"] and out[0]["input_dependencies"] == []
    bad = [row(1, 1, "a", "x", reference_sources=[{"source_step_id": "1-2"}]), row(1, 2, "b", "y")]
    with pytest.raises(ValueError, match="앞 단계가 아닙니다"):
        attach_dependencies(bad, [task(1, "c")])
