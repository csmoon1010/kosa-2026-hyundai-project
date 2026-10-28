"""시나리오 생성이 쓰는 그래프 — 사람이 확인한 그래프 + 화면 저장본, 그래프 고르기."""
import json
from pathlib import Path

from tap.cli import plan_request
from tap.goal.extract import choose_graph, graph_messages
from tap.graph.build import load_graphs

ROOT = Path(__file__).resolve().parents[1]

# 상태 그래프 만들기 화면이 저장하는 형식 (prototype/graph-editor.js yaml())
DRAFT = '''# 상품판매 그래프 — 화면에서 저장 (승인본 v1)
version: 1
graph:
  id: ITEM_SELL_GBCD
  name: "상품판매"
  domain: pd
  entity: "판매상품"
  state_field: itemSellGbcd
  entry_states: []
  verify_key_fields: []
code_group:
  id: ITEM_SELL_GBCD
  name: "상품판매구분코드"
  codes:
    "00": "판매중"
    "11": "일시중단"
    "19": "영구중단"
transitions:
  - name: "판매 일시중단"
    from: "00"
    to: "11"
    api: "hshop-openapi:POST:/pd/pdc/updateVenSellItemList.do"
    selector: {itemSellGbcd: "11"}
    api_status: 찾음
  - name: "영구중단"
    from: "00"
    to: "19"
    api: "hshop-openapi:POST:/pd/pdc/updateVenSellItemList.do"
    selector: {itemSellGbcd: "19"}
    api_status: 찾음
  - name: "아무 이름"
    from: "11"
    to: "19"
    api: null    # API 후보 없음 — 개발 담당자 검수
    selector: {}
    api_status: 없음
lookups:
  - api: "hshop-openapi:POST:/pd/pdc/selectVenSellItemQryList.do"
    selector: {itemSellGbcdIn: "00"}
    states: ["00"]
  - api: "hshop-openapi:POST:/pd/pdc/selectVenSellItemQryList.do"
    selector: {itemSellGbcdIn: "19"}
    states: ["19"]
layout:
  "00": [85, 150]
'''


def drafts(tmp_path):
    d = tmp_path / "graphs"
    d.mkdir()
    (d / "ITEM_SELL_GBCD.yaml").write_text(DRAFT, encoding="utf-8")
    return d


def test_load_graphs_knowledge_and_drafts(tmp_path):
    graphs, notes = load_graphs([ROOT / "data/knowledge", drafts(tmp_path)])
    ids = [g.graph_id for g in graphs]
    assert {"ORD_STAT_GBCD", "SLITM_APRVL_GBCD", "ITEM_ATHZ_GBCD", "ITEM_SELL_GBCD"} <= set(ids)
    sell = next(g for g in graphs if g.graph_id == "ITEM_SELL_GBCD")
    assert len(sell.edges) == 2 and "API 를 못 찾은 화살표 1개" in notes[0]       # api: null 은 뺀다


def test_draft_overrides_knowledge_with_same_id(tmp_path):
    d = drafts(tmp_path)
    (d / "ord.yaml").write_text(DRAFT.replace("ITEM_SELL_GBCD", "ORD_STAT_GBCD").replace('"상품판매"', '"주문상태 (화면 저장본)"'), encoding="utf-8")
    graphs, _ = load_graphs([ROOT / "data/knowledge", d])
    assert next(g for g in graphs if g.graph_id == "ORD_STAT_GBCD").name == "주문상태 (화면 저장본)"


def test_choose_graph(tmp_path):
    graphs, _ = load_graphs([ROOT / "data/knowledge", drafts(tmp_path)])
    assert "ITEM_SELL_GBCD: 상품판매 — 대상 판매상품 · 상태 판매중, 일시중단, 영구중단" in graph_messages("x", graphs)[0]["content"]
    pick = lambda gid: (lambda messages, schema: schema(graph_id=gid, reason="판매중지라서"))
    g, why = choose_graph("판매중인 상품 영구중단해줘", graphs, pick("ITEM_SELL_GBCD"))
    assert (g.graph_id, why) == ("ITEM_SELL_GBCD", "판매중지라서")
    assert choose_graph("정산 확정된 건", graphs, pick("없음"))[0] is None
    one = [g]
    assert choose_graph("x", one, None) == (g, "그래프가 하나뿐")                      # 하나면 LLM 을 부르지 않는다


def test_plan_request_on_draft_graph(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for f in ("api_operations.json", "api_metadata.json", "api_catalog.json"):
        (out / f).write_text((ROOT / "data/out" / f).read_text(encoding="utf-8"), encoding="utf-8")
    goal = json.dumps({"graph_id": "ITEM_SELL_GBCD", "target": "19", "count": 1})
    ir = plan_request("판매중인 상품 하나 영구중단해줘", [ROOT / "data/knowledge", drafts(tmp_path)], out, goal_json=goal)["ir"]
    assert ir.status == "ok" and ir.graph_id == "ITEM_SELL_GBCD"
    lk, call, vf = ir.steps
    assert lk.params["itemSellGbcdIn"].value == "00"                                    # 판매중(00) 상품을 찾아서
    assert call.params["itemSellGbcd"].value == "19" and call.params["slitmCd"].ref == "step1.slitmCd"
    assert vf.params["itemSellGbcdIn"].value == "19" and vf.params["slitmCd"].ref == "step1.slitmCd"   # 키 없는 그래프는 넘긴 값으로 확인
    assert ir.alternative.writes == 0                                                    # 영구중단 상품을 바로 찾기
