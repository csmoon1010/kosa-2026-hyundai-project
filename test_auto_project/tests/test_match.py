"""화살표 · 상태 → API 후보 찾기 — 업무 담당자는 API 를 고르지 않는다."""
import json
from pathlib import Path

import pytest
import yaml

from tap.cli import build
from tap.graph.match import evaluate, match_edge, match_lookup, sim, status_of

ROOT = Path(__file__).resolve().parents[1]
GOLD = yaml.safe_load((ROOT / "data/knowledge/ord_stat.yaml").read_text(encoding="utf-8"))
SCOPE = ["pd", "od", "ds"]


def j(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spec_only(tmp_path_factory):
    d = tmp_path_factory.mktemp("spec_only")
    (d / "ov.yaml").write_text("apis: {}\n", encoding="utf-8")
    build(ROOT / "data/specs/hmall-openapi.json", d, ROOT / "data/config/domains.yaml",
          ROOT / "data/config/services.yaml", d / "ov.yaml", now="2026-10-27T10:00:00+09:00")
    return j(d / "api_metadata.json"), j(d / "api_operations.json")


def test_sim_reverse_word_penalty():
    assert sim("출고완료", "출고완료") == 1.0
    assert sim("배송완료취소", "배송완료") < 0.45 < sim("배송완료", "배송완료처리")


def test_repo_metadata_matches_all_order_edges():
    r = evaluate(GOLD, j(ROOT / "data/out/api_metadata.json"), j(ROOT / "data/out/api_operations.json"), SCOPE)
    assert r["summary"]["전이"]["1순위 정확"] == 6 and r["summary"]["조회"]["1순위 정확"] == 8


def test_spec_only_is_partial_but_never_confidently_wrong(spec_only):
    meta, ops = spec_only
    r = evaluate(GOLD, meta, ops, SCOPE)
    assert r["summary"]["전이"]["1순위 정확"] == 3                     # P2 · P3 · PB1 — 명세 summary 에 이름이 있는 것
    wrong = [x for x in r["rows"] if x["result"] != "정확"]
    assert wrong and all(x["status"] != "찾음" for x in wrong)         # 틀린 건 '찾음'으로 나오지 않는다 → 개발 담당자 검수


def test_edge_without_name_uses_target_state():
    meta = j(ROOT / "data/out/api_metadata.json")
    c = match_edge(None, "출고", "배송완료", meta, SCOPE)
    assert (c[0].selector, status_of(c)) == ({"procGb": "P3"}, "찾음")


def test_lookup_needs_state_field():
    meta, ops = j(ROOT / "data/out/api_metadata.json"), j(ROOT / "data/out/api_operations.json")
    c = match_lookup("회수확인", "60", meta, ops, "lastDlvstPrgrGbcd", SCOPE)
    assert c[0].selector == {"prgrGb": "P1"} and "다른 상태와 함께" in " ".join(c[0].reasons)
    assert all(x.api_id.endswith(("selectOshpDtlList.do", "selectWtdwDtlList.do")) for x in c)


def test_lookup_by_state_field_filter():
    """판매상품조회는 요청에도 slitmAprvlGbcd 가 있어 상태 코드로 바로 거른다. itemAthzGbcd 는 응답에만 있다."""
    meta, ops = j(ROOT / "data/out/api_metadata.json"), j(ROOT / "data/out/api_operations.json")
    c = match_lookup("승인완료", "2", meta, ops, "slitmAprvlGbcd", SCOPE)
    assert (c[0].api_id.endswith("selectVenSellItemQryList.do"), c[0].selector, status_of(c)) == (True, {"slitmAprvlGbcd": "2"}, "찾음")
    c = match_lookup("승인완료", "80", meta, ops, "itemAthzGbcd", SCOPE)
    assert c[0].selector == {} and status_of(c) == "없음"          # 전체 조회 후 고르기 → 개발 담당자 확인


def test_product_graphs_load_with_codes_only():
    from tap.graph.build import load_knowledge
    for f, n in (("slitm_aprvl.yaml", 9), ("item_athz.yaml", 7)):
        g = load_knowledge(ROOT / "data/knowledge" / f)
        assert (g.domain, len(g.nodes), g.edges) == ("pd", n, [])


def test_write_api_that_sets_state_field_directly():
    """상품 판매구분 변경 요청은 요청에 itemSellGbcd 가 있어 도착 상태 코드를 넣으면 바로 바뀐다 — 이름이 달라도 찾는다."""
    meta, ops = j(ROOT / "data/out/api_metadata.json"), j(ROOT / "data/out/api_operations.json")
    c = match_edge("판매 잠시 멈춤", "판매중", "일시중단", meta, SCOPE, operations=ops, state_field="itemSellGbcd", to_code="11")
    assert (c[0].api_id.endswith("updateVenSellItemList.do"), c[0].selector, status_of(c)) == (True, {"itemSellGbcd": "11"}, "찾음")
    look = match_lookup("일시중단", "11", meta, ops, "itemSellGbcd", SCOPE)    # 조회는 목록 조건 itemSellGbcdIn 으로 거른다
    assert look[0].api_id.endswith("selectVenSellItemQryList.do") and look[0].selector == {"itemSellGbcdIn": "11"}


def test_tie_between_different_apis_needs_check():
    """'회수처리' 는 일반 회수처리와 티켓 회수처리가 같은 점수 — 하나로 정할 수 없으니 확인 필요."""
    meta = j(ROOT / "data/out/api_metadata.json")
    c = match_edge("회수처리", "회수요청", "회수집하", meta, SCOPE)
    assert c[0].score == c[1].score and c[0].api_id != c[1].api_id and status_of(c) == "확인 필요"
