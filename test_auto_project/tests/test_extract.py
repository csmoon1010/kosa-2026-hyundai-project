"""그래프 재료 추출 실험 — 공통코드 읽기 · 추출 결과 형식 · 채점 (LLM 없이)."""
import json
from pathlib import Path

import pytest
import yaml

from tap.cli import LOOP_GOALS, build
from tap.graph.build import graph_from_dict, load_knowledge
from tap.graph.extract import build_messages, extract_knowledge, extract_schema, load_code_table
from tap.graph.plan import Goal
from tap.graph.score import score

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "data/knowledge/ord_stat.yaml"
CODES = ROOT / "data/codes/common_codes.csv"
G = "ORD_STAT_GBCD"
OSHP = "hshop-openapi:POST:/sc/scb/scbd/multiOshpProcess.do"
BACK = "hshop-openapi:POST:/sc/scb/scbd/multiOshpBackProcess.do"
LOOK = "hshop-openapi:POST:/sc/scb/scbd/selectOshpDtlList.do"


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("out")
    build(ROOT / "data/specs/hmall-openapi.json", d, ROOT / "data/config/domains.yaml",
          ROOT / "data/config/services.yaml", ROOT / "data/config/overrides.yaml", now="2026-10-27T10:00:00+09:00")
    return d


def j(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def gold():
    return yaml.safe_load(KNOW.read_text(encoding="utf-8"))


def goals():
    return [Goal(graph_id=G, **g) for g in LOOP_GOALS]


def test_code_table_matches_golden():
    cg = load_code_table(CODES, G)
    assert cg["codes"] == {str(k): v for k, v in gold()["code_group"]["codes"].items()}
    assert list(cg["codes"])[:3] == ["10", "20", "25"]                       # 정렬순서대로


def test_graph_from_dict_same_as_file():
    assert graph_from_dict(gold()) == load_knowledge(KNOW)


def test_schema_limits_codes_and_apis(out):
    cg = load_code_table(CODES, G)
    schema = extract_schema(cg["codes"], [o["api_id"] for o in j(out / "api_operations.json")])
    t = {"api_id": OSHP, "name": "x", "from_code": "25", "to_code": "30", "basis": "spec", "evidence": "x"}
    with pytest.raises(Exception):
        schema(entity="주문", state_field=None, entry_states=["99"], verify_key_fields=[])   # 없는 코드
    with pytest.raises(Exception):
        schema(entity="주문", state_field=None, entry_states=[], verify_key_fields=[],
               transitions=[{**t, "api_id": "no:such:api"}])                                 # 없는 API
    assert "- 25 출고대기" in build_messages(cg, "## 명세")[0]["content"]


def fake_llm(payload):
    return lambda messages, schema: schema(**payload)


def _payload_from_gold(drop_last_back=False, wrong_p1=False):
    g = gold()
    sel = lambda s: (next(iter(s)), next(iter(s.values()))) if s else (None, None)
    ts = []
    for t in g["transitions"]:
        f, v = sel(t["selector"])
        ts.append({"api_id": t["api"], "selector_field": f, "selector_value": v, "name": t["name"],
                   "from_code": str(t["from"]), "to_code": str(t["to"]), "basis": "spec", "evidence": "x"})
    if wrong_p1:
        ts[0].update(from_code="20", name="주문확인")
    if drop_last_back:
        ts = ts[:-1]
    lks = [{"api_id": lk["api"], "selector_field": "prgrGb", "selector_value": lk["selector"]["prgrGb"],
            "states": [s for s in lk["states"] if s != "56"], "basis": "guess", "evidence": "x"}
           for lk in g["lookups"]]
    return {"entity": "주문", "state_field": "lastDlvstPrgrGbcd", "entry_states": ["25"],
            "verify_key_fields": ["ordNo", "ordPtcSeq"], "transitions": ts, "lookups": lks}


def test_perfect_extraction_scores_full(out):
    cg = load_code_table(CODES, G)
    got = extract_knowledge(cg, j(out / "api_operations.json"), j(out / "api_metadata.json"),
                            fake_llm(_payload_from_gold()), "od")
    assert got["graph"]["domain"] == "od" and got["transitions"][0]["source"] == "llm"
    s = score(gold(), got, goals())["summary"]
    assert s["transitions"] == {"정답": 6, "정확": 6, "틀림": 0, "없음": 0, "추가": 0}
    assert s["lookups"]["정확"] == 7                                           # 56 은 비교에서 뺌
    assert (s["fields"], s["paths"]) == (3, {"A": 4, "B": 4})


def test_score_finds_wrong_missing_and_path_change(out):
    cg = load_code_table(CODES, G)
    got = extract_knowledge(cg, j(out / "api_operations.json"), j(out / "api_metadata.json"),
                            fake_llm(_payload_from_gold(drop_last_back=True, wrong_p1=True)), "od")
    r = score(gold(), got, goals())
    by = {x["item"]: x for x in r["transitions"]}
    assert by["multiOshpProcess.do procGb=P1"]["status"] == "틀림"
    assert by["multiOshpProcess.do procGb=P1"]["got_name"] == "주문확인"
    assert by["multiOshpBackProcess.do procGb=PB3"]["status"] == "없음"
    assert r["summary"]["paths"]["A"] < 4                                      # P1 이 틀리면 경로도 달라진다
