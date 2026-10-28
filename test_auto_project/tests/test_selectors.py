"""API Metadata selectors — 자동 추출 · 사람 보정 합치기 · 검증 · 그래프 검사."""
import json
from pathlib import Path

import pytest

from tap.catalog.build import OverrideError
from tap.cli import build
from tap.graph.build import load_knowledge, validate_graph

ROOT = Path(__file__).resolve().parents[1]
SC = "hshop-openapi:POST:/sc/scb/scbd/"
OSHP, BACK = SC + "multiOshpProcess.do", SC + "multiOshpBackProcess.do"


def run(tmp_path, overrides, name="out"):
    ov = tmp_path / f"{name}.yaml"
    ov.write_text(json.dumps({"apis": overrides}, ensure_ascii=False), encoding="utf-8")   # JSON ⊂ YAML
    out = tmp_path / name
    build(ROOT / "data/specs/hmall-openapi.json", out, ROOT / "data/config/domains.yaml",
          ROOT / "data/config/services.yaml", ov, now="2026-10-27T10:00:00+09:00")
    meta = {m["api_id"]: m for m in json.loads((out / "api_metadata.json").read_text(encoding="utf-8"))}
    review = json.loads((out / "review_queue.json").read_text(encoding="utf-8"))
    return meta, review, out


def vals(m, field):
    s = next(s for s in m["selectors"] if s["field"] == field)
    return s["complete"], [(v["value"], v["name"], v["source"]) for v in s["values"]]


def test_auto_selectors(tmp_path):
    meta, review, _ = run(tmp_path, {})
    # summary 에 '이름(값)' 이 셋 → 값 목록 전부로 본다
    assert vals(meta[OSHP], "procGb") == (True, [("P1", "주문확인", "spec"), ("P2", "출고완료", "spec"), ("P3", "배송완료", "spec")])
    # 예시값 하나뿐 → 일부만 앎, summary 를 그 값의 일로
    assert vals(meta[BACK], "procGb") == (False, [("PB1", "출고취소처리", "spec")])
    # 조회 범위 구분은 이름을 비워 둔다
    assert vals(meta[SC + "selectOshpDtlList.do"], "prgrGb") == (False, [("P0", None, "spec")])
    # 행 처리 구분 (등록/수정)
    assert vals(meta["hshop-openapi:POST:/pd/pdd/multiItemQnaAnsw.do"], "rowFlag") == (False, [("I", None, "spec")])
    # 구분값 없음
    upd = meta["hshop-openapi:POST:/pd/pdb/updateItemByVen.do"]
    assert (upd["selectors"], upd["selectors_source"]) == ([], "auto")
    assert {r["api_id"] for r in review if r["item"] == "selectors"} >= {BACK, SC + "selectOshpDtlList.do"}
    assert OSHP not in {r["api_id"] for r in review if r["item"] == "selectors"}


def test_override_merges_and_keeps_spec_name(tmp_path):
    meta, review, _ = run(tmp_path, {
        OSHP: {"selectors": [{"field": "procGb", "values": [{"value": "P1", "name": "출고진행"}]}]},
        BACK: {"selectors": [{"field": "procGb", "values": [{"value": "PB2", "name": "출고완료취소"},
                                                            {"value": "PB3", "name": "배송완료취소", "aliases": ["배송취소"]}]}]},
        "hshop-openapi:POST:/pd/pdd/multiItemQnaAnsw.do": {"selectors": []},
    })
    p1 = meta[OSHP]["selectors"][0]["values"][0]
    assert (p1["name"], p1["aliases"], p1["source"]) == ("출고진행", ["주문확인"], "override")   # 명세 이름은 별칭으로
    assert meta[OSHP]["selectors_source"] == "override"
    complete, values = vals(meta[BACK], "procGb")
    assert complete and [v for v, _, _ in values] == ["PB1", "PB2", "PB3"]                  # 자동 PB1 + 보정 PB2 · PB3
    assert values[0][2] == "spec" and values[2][2] == "override"
    assert "배송취소" in meta[BACK]["search_text"] and "출고진행" in meta[OSHP]["search_text"]
    qna = meta["hshop-openapi:POST:/pd/pdd/multiItemQnaAnsw.do"]
    assert (qna["selectors"], qna["selectors_source"]) == ([], "override")                   # 사람이 '없음' 확인
    assert BACK not in {r["api_id"] for r in review if r["item"] == "selectors"}


@pytest.mark.parametrize("sel, msg", [
    ("procGb", "selectors 는 목록"),
    ([{"values": []}], "field 가 없음"),
    ([{"field": "noSuch"}], "요청 필드에 noSuch 가 없음"),
    ([{"field": "procGb", "complete": "yes"}], "complete 는 true/false"),
    ([{"field": "procGb", "values": [{"value": "P1", "label": "x"}]}], "모르는 키 'label'"),
    ([{"field": "procGb", "values": [{"name": "x"}]}], "value 가 없음"),
])
def test_selector_override_errors(tmp_path, sel, msg):
    with pytest.raises(OverrideError, match=msg):
        run(tmp_path, {OSHP: {"selectors": sel}})


def test_graph_checks_selector_against_metadata(tmp_path):
    _, _, out = run(tmp_path, {OSHP: {"selectors": [{"field": "procGb", "values": [{"value": "P1", "name": "출고진행"}]}]}})
    meta = json.loads((out / "api_metadata.json").read_text(encoding="utf-8"))
    ops = json.loads((out / "api_operations.json").read_text(encoding="utf-8"))
    issues = validate_graph(load_knowledge(ROOT / "data/knowledge/ord_stat.yaml"), meta, ops)
    msgs = {(i["level"], i["message"]) for i in issues}
    # BackProcess 는 PB1 만 알고 목록 미완성 → PB2 · PB3 는 경고
    assert ("warn", "구분값 procGb=PB2 가 API Metadata selectors 에 없음 (값 목록 미완성)") in msgs


def test_repo_overrides_make_order_graph_clean():
    meta = json.loads((ROOT / "data/out/api_metadata.json").read_text(encoding="utf-8"))
    ops = json.loads((ROOT / "data/out/api_operations.json").read_text(encoding="utf-8"))
    issues = validate_graph(load_knowledge(ROOT / "data/knowledge/ord_stat.yaml"), meta, ops)
    assert not [i for i in issues if "selectors" in i["message"]]
