"""1단계 사전 작업 — 파싱 · 분류 · Tool Registry · API Metadata · API Catalog."""
import json
from pathlib import Path

import pytest

from tap.catalog.build import (OverrideError, classify_domain, classify_kind, content_hash, entity_hint,
                               load_domain_rules, next_version)
from tap.cli import build
from tap.models import ApiOperation
from tap.registry.tools import infer_success_rule, resolve_conn
from tap.spec.parser import (DuplicateApiId, load_spec, make_api_id, parse_example, parse_operations,
                             split_dataset_id)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/specs/hmall-openapi.json"
RULES = ROOT / "data/config/domains.yaml"
SERVICES = ROOT / "data/config/services.yaml"
SVC = "hshop-openapi"
NOW = "2026-10-19T10:00:00+09:00"


@pytest.fixture(scope="module")
def ops():
    return parse_operations(load_spec(SPEC), SPEC.name, SVC)


def op_of(ops, operation_id) -> ApiOperation:
    return next(o for o in ops if o.operation_id == operation_id)


def aid(path: str) -> str:
    return make_api_id(SVC, "POST", path)


def run(tmp_path, overrides: dict | None = None, out: str = "out"):
    ov = tmp_path / "overrides.yaml"
    ov.write_text(json.dumps({"apis": overrides or {}}, ensure_ascii=False), encoding="utf-8")   # JSON ⊂ YAML
    r = build(SPEC, tmp_path / out, RULES, SERVICES, ov, now=NOW)

    def load(name):
        return json.loads((tmp_path / out / f"{name}.json").read_text(encoding="utf-8"))
    return r, load


# ------------------------------------------------------------ example 해석

@pytest.mark.parametrize("raw, expected", [
    ("진행구분코드(타입:string, 예:P1)", ("진행구분코드", "string", "P1")),
    ("사은품상품여부(타입:string, 예Y:)", ("사은품상품여부", "string", "Y")),     # 명세 오타
    ("판매상품코드(예:2015700001)", ("판매상품코드", None, "2015700001")),        # 타입 없음
    ("20160118617141(타입:string, 예:20160118617141)", (None, "string", "20160118617141")),  # 이름 자리에 값
    ("dsCond", (None, None, "dsCond")),
])
def test_parse_example(raw, expected):
    assert parse_example(raw) == expected


def test_split_dataset_note():
    assert split_dataset_id("dsItemHdmallImgUrl(백화점 상품 등록시에만 입력)") == \
        ("dsItemHdmallImgUrl", "백화점 상품 등록시에만 입력")
    assert split_dataset_id("dsInput") == ("dsInput", None)


# ------------------------------------------------------------------ 파싱 · api_id

def test_api_id_is_service_method_path(ops):
    assert len(ops) == 43 and len({o.api_id for o in ops}) == 43
    o = op_of(ops, "multiItem")
    assert o.api_id == "hshop-openapi:POST:/pd/pdb/multiItem.do"
    assert (o.service, o.spec_source) == (SVC, SPEC.name)


def test_same_operation_id_different_path_ok():
    """operationId 가 겹쳐도 경로가 다르면 api_id 는 다르다."""
    spec = {"paths": {"/a": {"post": {"operationId": "x"}}, "/b": {"post": {"operationId": "x"}}}}
    assert {o.api_id for o in parse_operations(spec, "s.json", "svc")} == {"svc:POST:/a", "svc:POST:/b"}


def test_duplicate_api_id_fails(monkeypatch):
    """같은 api_id 가 나오면 이름을 바꿔 덮지 않고 빌드를 멈춘다."""
    from tap.spec import parser
    monkeypatch.setattr(parser, "make_api_id", lambda s, m, p: "same")
    spec = {"paths": {"/a": {"post": {}}, "/b": {"post": {}}}}
    with pytest.raises(DuplicateApiId):
        parse_operations(spec, "s.json", "svc")


def test_xml_dataset_fields(ops):
    o = op_of(ops, "multiOshpProcess")
    assert o.request_content_type == "application/xml"
    assert [h.name for h in o.headers] == ["oauserId", "oauseKey"]
    assert o.request_datasets == ["dsInput"]
    proc = next(f for f in o.request_fields if f.name == "procGb")
    assert (proc.label, proc.example, proc.dataset_id) == ("진행구분코드", "P1", "dsInput")


def test_dataset_notes_kept(ops):
    assert op_of(ops, "multiItem").dataset_notes == {"dsItemHdmallImgUrl": "백화점 상품 등록시에만 입력"}


def test_labels_mostly_found(ops):
    fields = [f for o in ops for f in o.request_fields]
    assert sum(1 for f in fields if not f.label) / len(fields) < 0.01


# ------------------------------------------------------------------ 분류

def test_domain_by_prefix(ops):
    rules = load_domain_rules(RULES)
    g = {o.operation_id: classify_domain(o, rules) for o in ops}
    assert (g["multiItem"].domain, g["multiItem"].confidence) == ("pd", "높음")
    assert g["multiOshpProcess"].domain == "ds"                    # /sc → 물류/SCM
    assert g["insertVenAdrMng"].domain == "af"                     # /vd → 재경
    for oid in ("multiVenSdlvcMngInf", "selectSectMstList"):       # /hmgb · /om 미지정
        assert (g[oid].domain, g[oid].confidence) == ("unknown", "낮음")


def test_domain_rules_validation(tmp_path):
    rules = load_domain_rules(RULES)
    assert rules["prefix"]["/pd"] == "pd" and rules["domains"]["ds"] == "물류/SCM"
    dup = tmp_path / "dup.yaml"
    dup.write_text("domains:\n  a: {name: A, prefixes: [/x]}\n  b: {name: B, prefixes: [/x/]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="두 도메인"):
        load_domain_rules(dup)
    multi = tmp_path / "multi.yaml"
    multi.write_text("domains:\n  a: {name: A, prefixes: [/x, /y]}\n", encoding="utf-8")
    assert load_domain_rules(multi)["prefix"] == {"/x": "a", "/y": "a"}


def test_prefix_is_segment(ops):
    rules = {"domains": {"hm": "전시"}, "prefix": {"/hm": "hm"}, "tags": {}}
    assert classify_domain(op_of(ops, "multiVenSdlvcMngInf"), rules).domain == "unknown"   # /hmgb ≠ /hm


@pytest.mark.parametrize("oid, kind, action", [
    ("selectItem", "read", "조회"), ("multiItem", "write", "등록"),
    ("updateVenSellItemList", "write", "요청"), ("multiOshpProcess", "write", "처리"),
    ("getSdlvcVenMngDtlList", "read", "조회"),
])
def test_kind(ops, oid, kind, action):
    assert classify_kind(op_of(ops, oid))[:2] == (kind, action)


def test_entity_hint_keeps_inner_words(ops):
    assert entity_hint(op_of(ops, "selectInfNotfBsicDtlList")) == "상품필수정보"
    assert entity_hint(op_of(ops, "selectCnclList")) == "취소"


# ------------------------------------------------------------- Tool Registry

def test_success_rule(ops):
    assert infer_success_rule(op_of(ops, "multiItem")) == {"path": "result/code", "equals": "0000"}
    assert infer_success_rule(op_of(ops, "multiOshpProcess")) == {"path": "result/result", "equals": "Request Success"}


def test_domain_conn_override():
    services = [{"name": "svc", "spec": "s.json",
                 "defaults": {"base_url": "BASE", "timeout_ms": 5000,
                              "auth": {"type": "API_KEY_HEADER", "profile": "p", "headers": ["k"]},
                              "allowed_environments": ["DEV", "STG", "PROD"]},
                 "domains": {"ds": {"timeout_ms": 12000, "base_url": "DS_BASE"}}}]
    ds = resolve_conn("s.json", "ds", services, "http://spec", ["k"])
    pd = resolve_conn("s.json", "pd", services, "http://spec", ["k"])
    none = resolve_conn("other.json", "pd", services, "http://spec", ["h1"])
    assert (ds.base_url, ds.timeout_ms, ds.source) == ("DS_BASE", 12000, "domain")
    assert (pd.base_url, pd.timeout_ms, pd.source) == ("BASE", 5000, "service")
    assert pd.allowed_environments == ["DEV", "STG"]               # 운영은 정책상 항상 제외
    assert (none.service, none.auth_headers, none.base_url_default, none.source) == \
        ("other", ["h1"], "http://spec", "spec")


# ------------------------------------------------------------ 전체 실행

def test_three_documents_linked_by_api_id(tmp_path):
    r, load = run(tmp_path)
    assert r["operations"] == 43 and r["kinds"] == {"read": 25, "write": 18}
    reg, meta, cat = load("tool_registry"), load("api_metadata"), load("api_catalog")
    ids = [t["api_id"] for t in reg["tools"]]
    assert len(set(ids)) == 43                                     # Tool Registry PK = api_id
    assert ids == [m["api_id"] for m in meta] == [a["api_id"] for a in cat["apis"]]
    assert "tool_id" not in reg["tools"][0] and "tool_id" not in meta[0] and "tool_name" not in meta[0]

    writes = {m["api_id"] for m in meta if m["kind"] == "write"}
    for t in reg["tools"]:                                         # 고정 규칙
        assert t["retry_count"] == (0 if t["api_id"] in writes else 2)
        assert t["approval_required"] == (t["api_id"] in writes)
        assert t["base_url"] == "HMALL_API_BASE_URL" and t["allowed_environments"] == ["DEV"]
    mi = next(t for t in reg["tools"] if t["api_id"] == aid("/pd/pdb/multiItem.do"))
    assert (mi["body_format"], mi["auth_type"], mi["auth_profile"]) == \
        ("nexacro-xml", "API_KEY_HEADER", "hmall-openapi-key")

    m = next(x for x in meta if x["api_id"] == aid("/pd/pdb/multiItem.do"))
    assert (m["description"], m["irreversible"], m["input_concepts"], m["output_concepts"]) == (None, "미확인", [], [])
    assert m["document_id"] == SPEC.name and m["spec_hash"].startswith("sha256:")
    assert set(cat["apis"][0]) == {"api_id", "operation_id", "api_name", "description", "domain", "kind",
                                   "aliases", "tool_enabled"}
    assert cat["spec_sources"] == [{"service": SVC, "document_id": SPEC.name, "spec_hash": m["spec_hash"]}]


def test_overrides_and_versions(tmp_path):
    api = aid("/pd/pdb/multiItem.do")
    _, load = run(tmp_path)
    v1 = load("api_catalog")
    _, load = run(tmp_path)                                        # 같은 입력 → 버전 그대로
    assert load("api_catalog")["catalog_version"] == v1["catalog_version"] == 1

    _, load = run(tmp_path, {api: {"aliases": ["상품 생성"], "memo": "단건 등록", "irreversible": "가능",
                                   "enabled": False}})
    cat, meta, reg = load("api_catalog"), load("api_metadata"), load("tool_registry")
    assert cat["catalog_version"] == 2                             # 내용이 바뀌면 +1
    m = next(x for x in meta if x["api_id"] == api)
    assert (m["aliases"], m["memo"], m["irreversible"], m["metadata_version"]) == (["상품 생성"], "단건 등록", "가능", 2)
    assert "상품 생성" in m["search_text"] and "단건 등록" in m["search_text"]   # 별칭 · 구별 메모로도 검색
    assert next(t for t in reg["tools"] if t["api_id"] == api)["enabled"] is False
    assert next(a for a in cat["apis"] if a["api_id"] == api)["tool_enabled"] is False     # 원본에서 복사
    other = next(x for x in meta if x["api_id"] == aid("/pd/pdb/selectItem.do"))
    assert other["metadata_version"] == 1                          # 안 바뀐 API 는 그대로


def test_version_helpers():
    assert next_version(None, None, "h") == 1
    assert next_version(3, "h", "h") == 3 and next_version(3, "h", "x") == 4
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


@pytest.mark.parametrize("ov, msg", [
    ({"api_name": "새 이름"}, "모르는 키 'api_name'"),
    ({"tool_enabled": False}, "'enabled' 를 쓰세요"),               # 문서상 이름을 적은 실수 → 힌트
    ({"irreversible": "아니오"}, "irreversible 는 미확인 · 가능 · 불가"),
    ({"aliases": "상품 생성"}, "aliases 는 문자열 목록"),
    ({"enabled": "false"}, "enabled 는 true/false"),
    ({"success_rule": {"path": "result/code"}}, "success_rule 은"),
])
def test_override_errors_fail_build(tmp_path, ov, msg):
    with pytest.raises(OverrideError, match=msg):
        run(tmp_path, {aid("/pd/pdb/multiItem.do"): ov})


def test_override_unknown_api_id_fails(tmp_path):
    with pytest.raises(OverrideError, match="명세에 없는 api_id"):
        run(tmp_path, {aid("/pd/pdb/notExists.do"): {"memo": "x"}})
