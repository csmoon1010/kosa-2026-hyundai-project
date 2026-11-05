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
