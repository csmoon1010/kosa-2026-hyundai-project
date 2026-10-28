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
    assert d["ai"]["ORD_STAT_GBCD"]["model"] == "gpt-5.5" and d["ai"]["ORD_STAT_GBCD"]["questions"]
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


def test_server_plan_without_llm(server):
    base, _ = server
    ir = json.loads(call(base + "/api/plan", {"utterance": "출고된 주문 1건 만들어줘.",
                                              "goal": {"graph_id": "ORD_STAT_GBCD", "target": "45"}}))
    assert ir["status"] == "ok" and [s["kind"] for s in ir["steps"]] == ["lookup", "call", "call", "verify"]


def test_server_graph_save_writes_out_not_knowledge(server):
    base, root = server
    r = json.loads(call(base + "/api/graph/save", {"graph_id": "ORD_STAT_GBCD/../x", "yaml": "graph: {}\n"}))
    assert r["file"] == "data/out/graphs/ORD_STAT_GBCDx.yaml" and (root / r["file"]).read_text() == "graph: {}\n"
