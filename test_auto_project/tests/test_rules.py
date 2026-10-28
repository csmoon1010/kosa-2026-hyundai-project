"""화면 규칙(rules.ui.yaml) — 형식 검사 · overrides 로 바꾸기 · 빌드에 합치기 · 서버 저장."""
import json
import urllib.error

import pytest

from tap.catalog.rules import RuleError, add_rule, check_rule, merge_overrides, parse_selector, rule_overrides
from test_ui import call, server  # noqa: F401  (픽스처 재사용)

BACK = "hshop-openapi:POST:/sc/scb/scbd/multiOshpBackProcess.do"
ITEM = "hshop-openapi:POST:/pd/pdb/multiItem.do"


def test_parse_selector():
    assert parse_selector("procGb: PB2 출고완료취소 · PB3 배송완료취소") == {
        "field": "procGb", "complete": True, "values": [{"value": "PB2", "name": "출고완료취소"}, {"value": "PB3", "name": "배송완료취소"}]}
    assert parse_selector("rowFlag: I 등록, U (일부)")["complete"] is False
    with pytest.raises(RuleError):
        parse_selector("PB2 출고완료취소")


def test_rule_overrides_and_merge():
    rules = [{"doc": "cat", "item": "kw", "target": ITEM, "body": "상품 생성, 신규 상품"},
             {"doc": "cat", "item": "desc", "target": ITEM, "body": "단건 등록"},
             {"doc": "meta", "item": "irrev", "target": BACK, "body": "불가 외부 전송"},
             {"doc": "meta", "item": "sel", "target": BACK, "body": "procGb: PB9 테스트"},
             {"doc": "pkb", "item": "meaning", "target": "ordNo", "body": "주문번호"}]          # pkb 는 overrides 로 가지 않는다
    ov = rule_overrides(rules)
    assert ov[ITEM] == {"aliases": ["상품 생성", "신규 상품"], "description": "단건 등록"}
    assert ov[BACK]["irreversible"] == "불가" and ov[BACK]["selectors"][0]["values"] == [{"value": "PB9", "name": "테스트"}]
    m = merge_overrides({ITEM: {"aliases": ["상품 등록"], "memo": "x"}}, ov)
    assert m[ITEM]["aliases"] == ["상품 등록", "상품 생성", "신규 상품"] and m[ITEM]["memo"] == "x"


def test_add_rule_replaces_same_place_but_keeps_many_aliases():
    r = add_rule([], {"place": "ov", "doc": "cat", "item": "desc", "dom": "order", "target": ITEM, "body": "a"})
    r = add_rule(r, {"place": "ov", "doc": "cat", "item": "desc", "dom": "order", "target": ITEM, "body": "b"})
    assert [x["body"] for x in r] == ["b"]
    r = add_rule(r, {"place": "ov", "doc": "cat", "item": "kw", "dom": "order", "target": ITEM, "body": "x"})
    r = add_rule(r, {"place": "ov", "doc": "cat", "item": "kw", "dom": "order", "target": ITEM, "body": "y"})
    assert len(r) == 3 and len({x["id"] for x in r}) == 3
    with pytest.raises(RuleError, match="불가 · 가능 · 미확인"):
        check_rule({"doc": "meta", "item": "irrev", "target": BACK, "body": "안됨"})


def meta_of(data, api):
    return next(m for m in data["metadata"] if m["api_id"] == api)


def test_server_rule_saves_rebuilds_and_deletes(server):  # noqa: F811
    base, root = server
    r = json.loads(call(base + "/api/rules", {"place": "ov", "doc": "meta", "item": "memo", "dom": "goods", "target": ITEM, "body": "단건 등록 전용"}))
    assert meta_of(r["data"], ITEM)["memo"] == "단건 등록 전용" and r["data"]["rules"][0]["by"] == "화면"
    assert "단건 등록 전용" in (root / "data/config/rules.ui.yaml").read_text(encoding="utf-8")
    r = json.loads(call(base + "/api/rules", {"place": "ov", "doc": "meta", "item": "sel", "dom": "order", "target": BACK, "body": "procGb: PB4 테스트취소"}))
    assert [v["value"] for v in meta_of(r["data"], BACK)["selectors"][0]["values"]] == ["PB1", "PB2", "PB3", "PB4"]
    rid = r["data"]["rules"][-1]["id"]
    r = json.loads(call(base + "/api/rules/delete", {"id": rid}))
    assert [v["value"] for v in meta_of(r["data"], BACK)["selectors"][0]["values"]] == ["PB1", "PB2", "PB3"]


def test_server_rejects_bad_rule_and_keeps_file(server):  # noqa: F811
    base, root = server
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base + "/api/rules", {"place": "ov", "doc": "meta", "item": "sel", "dom": "order", "target": BACK, "body": "noSuchField: X 이름"})
    assert e.value.code == 400 and "noSuchField" in json.loads(e.value.read())["error"]
    assert not (root / "data/config/rules.ui.yaml").exists() or "noSuchField" not in (root / "data/config/rules.ui.yaml").read_text(encoding="utf-8")


def test_server_baseline(server):  # noqa: F811
    base, root = server
    r = json.loads(call(base + "/api/baseline", {"api_id": BACK, "body": {"procGb": "PB1", "ordNo": "20240101000001"}}))
    assert r["data"]["baselines"][BACK]["body"]["procGb"] == "PB1" and (root / r["file"]).exists()
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base + "/api/baseline", {"api_id": BACK, "body": {"noSuch": "1"}})
    assert e.value.code == 400 and "noSuch" in json.loads(e.value.read())["error"]


def test_server_scenario_and_run(server):  # noqa: F811
    base, root = server
    ir = json.loads(call(base + "/api/plan", {"utterance": "출고된 주문 1건 만들어줘.", "goal": {"graph_id": "ORD_STAT_GBCD", "target": "45"}}))
    r = json.loads(call(base + "/api/scenarios", {"name": "출고 주문", "utterance": ir["request"], "domains": ["order"], "ir": ir}))
    sc = r["scenario"]
    assert [x["id"] for x in r["data"]["scenarios"]] == [sc["id"]] and (root / "data/scenarios" / f"{sc['id']}.json").exists()
    rej = json.loads(call(base + "/api/plan", {"utterance": "결제완료", "goal": {"graph_id": "ORD_STAT_GBCD", "target": "20"}}))
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base + "/api/scenarios", {"name": "x", "ir": rej})
    assert e.value.code == 400 and "거절" in json.loads(e.value.read())["error"]
    run = json.loads(call(base + "/api/runs", {"rows": [{"scenario_id": sc["id"], "count": 1}], "calls": [{"api": "a"}]}))
    assert run["run"]["kind"] == "드라이런" and run["data"]["runs"][0]["id"] == run["run"]["id"]
    r = json.loads(call(base + "/api/scenarios/delete", {"id": sc["id"]}))
    assert r["data"]["scenarios"] == []


def test_synonyms_reach_goal_prompt():
    from pathlib import Path
    from tap.catalog.rules import synonyms_of
    from tap.goal.extract import build_messages
    from tap.graph.build import load_knowledge
    rules = [{"doc": "sv", "item": "syn", "target": "ORD_STAT_GBCD:30", "body": "피킹 중, 출고 작업 중"},
             {"doc": "sv", "item": "syn", "target": "ORD_STAT_GBCD:30", "body": "피킹 중 · 포장 중"},
             {"doc": "sv", "item": "syn", "target": "ITEM_SELL_GBCD:11", "body": "판매 멈춤"}]
    syn = synonyms_of(rules, "ORD_STAT_GBCD")
    assert syn == {"30": ["피킹 중", "출고 작업 중", "포장 중"]}                       # 그래프별 · 여러 규칙 합침
    g = load_knowledge(Path(__file__).resolve().parents[1] / "data/knowledge/ord_stat.yaml")
    next(n for n in g.nodes if n.code == "30").synonyms = syn["30"]
    assert "- 출고진행 (30) · 다른 표현: 피킹 중, 출고 작업 중, 포장 중" in build_messages("x", g)[0]["content"]
