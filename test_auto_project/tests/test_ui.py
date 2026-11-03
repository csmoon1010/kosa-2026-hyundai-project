"""오프라인 UI 에 입히는 실제 산출물 · 로컬 서버."""
import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tap.ui.export import ui_data, write_ui_data
from tap.ui.serve import make_handler

ROOT = Path(__file__).resolve().parents[1]


def test_ui_data_has_implemented_areas():
    d = ui_data(ROOT)
    assert len(d["metadata"]) == len(d["catalog"]) == len(d["tools"]) == d["build"]["operations"] == 42
    doms = {g["graph"]["id"]: g["graph"]["domain"] for g in d["graphs"]}
    assert doms == {"ORD_STAT_GBCD": "od", "SLITM_APRVL_GBCD": "pd", "ITEM_ATHZ_GBCD": "pd"}
    assert "ai" not in d                                                               # 그래프 캔버스는 노드 흐름만 — AI 제안을 주지 않는다
    assert {o["kind"] for o in d["ops"]} == {"read", "write"} and all(len(f) == 3 for o in d["ops"] for f in o["req"])
    groups = {g["id"]: g for g in d["codes"]}
    assert set(groups) >= set(doms) and groups["SLITM_APRVL_GBCD"]["order"][:3] == ["0", "1", "2"]   # 정렬순서 유지
    assert d["drafts"] == [] or all("graph" in x for x in d["drafts"])
    back = next(m for m in d["metadata"] if m["api_id"].endswith("multiOshpBackProcess.do"))
    assert [v["value"] for v in back["selectors"][0]["values"]] == ["PB1", "PB2", "PB3"]


def test_write_ui_data(tmp_path):
    p = write_ui_data(ROOT, tmp_path / "tap-data.js")
    s = p.read_text(encoding="utf-8")
    assert s.splitlines()[1].startswith("window.TAP_DATA = ") and json.loads(s.split("= ", 1)[1].rstrip().rstrip(";"))["graphs"]


@pytest.fixture()
def server(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(ROOT / "data", root / "data")
    (root / "prototype").mkdir()
    (root / "prototype" / "offline-ui.html").write_text("<p>ui</p>", encoding="utf-8")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", root
    httpd.shutdown()


def call(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8")


def test_server_health_static_and_data(server):
    base, _ = server
    assert json.loads(call(base + "/api/health")) == {"ok": True}
    assert call(base + "/") == "<p>ui</p>"
    assert call(base + "/tap-data.js").startswith("window.TAP_DATA = ")


def test_server_graph_save_merges_into_data_graphs(server):
    import urllib.error
    import yaml
    from tap.graph.build import load_graphs
    base, root = server
    with pytest.raises(urllib.error.HTTPError) as e:                                     # id 가 맞지 않으면 쓰지 않는다
        call(base + "/api/graph/save", {"graph_id": "ORD_STAT_GBCD/../x", "yaml": "graph: {id: ORD_STAT_GBCD}\n"})
    assert e.value.code == 400
    old = yaml.safe_load((root / "data/graphs/ORD_STAT_GBCD.yaml").read_text(encoding="utf-8"))
    screen = dict(old, version=1, graph=dict(old["graph"], entry_states=[]), layout={"25": [0, 0]},
                  transitions=[dict(t, api="x:POST:/wrong.do") for t in old["transitions"]], lookups=[{"api": "x", "selector": {}, "states": ["25"]}])
    r = json.loads(call(base + "/api/graph/save", {"graph_id": "ORD_STAT_GBCD", "yaml": "# 화면에서 저장\n" + yaml.safe_dump(screen, allow_unicode=True)}))
    assert r["file"] == "data/graphs/ORD_STAT_GBCD.yaml" and r["backup"].startswith("data/out/graph_history/ORD_STAT_GBCD.")
    saved = yaml.safe_load((root / r["file"]).read_text(encoding="utf-8"))
    assert saved["graph"]["entry_states"] == ["25"]                                     # 화면이 비워 보낸 그래프 칸은 유지
    assert all(set(t) <= {"name", "from", "to", "kind"} for t in saved["transitions"]) and "lookups" not in saved   # 노드 흐름만
    assert (root / r["backup"]).read_text(encoding="utf-8").startswith("# 주문상태 그래프")      # 이전 파일은 이력에
    new = {"version": 1, "graph": {"id": "ITEM_SELL_GBCD", "name": "상품판매", "domain": "pd", "entity": "판매상품"},
           "code_group": {"id": "ITEM_SELL_GBCD", "name": "상품판매구분코드", "codes": {"00": "판매중", "19": "영구중단"}},
           "transitions": [], "lookups": [], "layout": {"00": [0, 0]}}
    r2 = json.loads(call(base + "/api/graph/save", {"graph_id": "ITEM_SELL_GBCD", "yaml": yaml.safe_dump(new, allow_unicode=True)}))
    assert r2["backup"] is None and r2["file"] == "data/graphs/ITEM_SELL_GBCD.yaml"
    ids = {g.graph_id for g in load_graphs([root / "data/graphs"])[0]}
    assert ids == {"ORD_STAT_GBCD", "SLITM_APRVL_GBCD", "ITEM_ATHZ_GBCD", "ITEM_SELL_GBCD"}
    d = json.loads(call(base + "/tap-data.js").split("= ", 1)[1].rstrip().rstrip(";"))
    assert {x["graph"]["id"] for x in d["drafts"]} == {"ORD_STAT_GBCD", "ITEM_SELL_GBCD"}         # 화면에서 저장한 것만 저장본


Q = "배송완료된 주문 3건을 배송완료 취소시켜줘"


def fake_llm(messages, schema):
    """① 의도 분석 · ② 상태 고르기 — 주문상태 API 는 고정이라 ③ LLM 은 부르지 않는다."""
    if schema.__name__ == "TaskPlanOut":
        return schema.model_validate({"original_question": Q, "unresolved": [], "tasks": [
            {"sequence": 1, "domain": "OD", "origin": "기존", "action": "배송완료취소", "conditions": "c", "constraints": [],
             "depends_on": [], "count": 3, "source_phrases": [Q]}]})
    return schema.model_validate({"unresolved": [], "choices": [
        {"sequence": 1, "graph_id": "ORD_STAT_GBCD", "from_state": "배송완료", "to_state": "출고", "must_pass": [],
         "state_phrases": ["배송완료된 주문"], "reason": "r"}]})


@pytest.fixture()
def agent_server(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(ROOT / "data", root / "data")
    (root / "prototype").mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, llm=fake_llm))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", root
    httpd.shutdown()


def test_server_select_and_approval_gate(agent_server):
    import urllib.error
    base, root = agent_server
    r = json.loads(call(base + "/api/select", {"utterance": Q}))
    assert r["tasks"]["tasks"][0]["action"] == "배송완료취소" and r["paths"]["paths"][0]["to_state"] == "출고"
    assert [x["selection_status"] for x in r["apis"]["api_selection_results"]] == ["선택", "선택"]
    g = r["gate"]
    assert g["status"] == "승인 필요" and [s["tier"] for s in g["steps"]] == ["R0", "R1"]
    assert [s["name"] for s in r["trace"]["spans"]] == ["① 의도 분석", "② 경로 탐색", "③ API 선택"] and r["trace"]["totals"]["llm_calls"] == 2
    h = g["selection_hash"]
    with pytest.raises(urllib.error.HTTPError) as e:                                     # 승인 없이 실행 → 거부
        call(base + "/api/run", {"selection_hash": h})
    assert e.value.code == 400 and "승인 없이 실행할 수 없습니다" in json.loads(e.value.read().decode("utf-8"))["error"]
    with pytest.raises(urllib.error.HTTPError) as e:                                     # 승인이 모자람 → 거부
        call(base + "/api/approve", {"selection_hash": h, "scenario": False})
    body = json.loads(e.value.read().decode("utf-8"))
    assert body["refused"] and "시나리오 승인" in body["error"]
    ok = json.loads(call(base + "/api/approve", {"selection_hash": h, "scenario": True, "approver": "지은"}))
    assert ok["approval"]["approver"] == "지은" and ok["confirm_steps"] == [] and (root / ok["file"]).exists()
    run = json.loads(call(base + "/api/run", {"selection_hash": h, "confirm": []}))      # R1 만 — 실행 때 추가 확인 없음
    assert [c["key"] for c in run["calls"]] == ["1-0", "1-1"]
    with pytest.raises(urllib.error.HTTPError) as e2:                                    # 서버가 모르는 결과는 승인 불가
        call(base + "/api/approve", {"selection_hash": "sha256:가짜", "scenario": True})
    assert "서버가 모릅니다" in json.loads(e2.value.read().decode("utf-8"))["error"]


def test_approval_hands_off_to_ir_draft(agent_server):
    """승인해야만 혜정 IR 초안 생성의 입력(prototype/approved/tdg-*.json)이 생긴다 — 혜정 fixed_plan 으로 읽을 수 있는 형식."""
    from tap.ir.draft_build import fixed_plan
    base, root = agent_server
    r = json.loads(call(base + "/api/select", {"utterance": Q}))
    assert not (root / "prototype/approved").exists()                                   # 승인 전에는 없음
    ok = json.loads(call(base + "/api/approve", {"selection_hash": r["gate"]["selection_hash"], "scenario": True}))
    h = ok["ir_handoff"]
    assert h["filename"].startswith("tdg-") and [(x["source_step"], x["step_id"]) for x in h["steps"]] == [("1-0", "1-1"), ("1-1", "1-2")]
    data = json.loads((root / h["file"]).read_text(encoding="utf-8"))
    assert data["approval_status"] == "approved" and data["intent_tasks"][0]["domain"] == "OD"
    rows = data["api_selection_results"]
    assert [x["selector"] for x in rows] == [{"prgrGb": "P3"}, {"procGb": "PB3"}] and all(x["approval_status"] == "approved" for x in rows)
    assert [s["step_id"] for s in fixed_plan(data)] == ["1-1", "1-2"]
    listed = json.loads(call(base + "/api/approved-selections"))["files"]               # 혜정 화면의 승인본 목록에 보인다
    assert any(f["filename"] == h["filename"] and f["approval_status"] == "approved" for f in listed)
