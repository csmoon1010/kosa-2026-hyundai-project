"""로컬 서버 — 오프라인 UI 를 띄우고, 구현된 기능은 실제로 실행한다.

    PYTHONPATH=src python -m tap.cli serve        → http://127.0.0.1:8765/offline-ui.html

  GET  /tap-data.js          산출물을 매번 새로 읽어 내려준다
  GET  /api/health           화면이 서버 모드인지 확인
  POST /api/plan             {utterance, goal?} → 목표 추출(LLM) → 경로 → Scenario IR (goal 을 주면 LLM 없이)
  POST /api/graph/save       {graph_id, yaml} → data/out/graphs/<id>.yaml (정답지 data/knowledge 는 건드리지 않는다)
  POST /api/rules            {place, doc, item, dom, target, body} → data/config/rules.ui.yaml + 다시 빌드 → 새 TAP_DATA
  POST /api/rules/delete     {id} → 화면 규칙 삭제 + 다시 빌드
  POST /api/baseline         {api_id, body} → data/baselines/<api>.json
  POST /api/build            명세 · 설정을 다시 읽어 빌드 (최신화 · 변경 확인)
  POST /api/scenarios        {name, utterance, domains, ir} → data/scenarios/<id>.json (확인 후 저장 = 승인본 고정)
  POST /api/scenarios/delete {id}
  POST /api/runs             {rows, steps, unresolved} → data/runs/<id>.json (드라이런 — 실제 API 호출 없음)
"""
from __future__ import annotations

import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tap.ui.export import ui_data


def rebuild(root: Path) -> dict:
    """1단계 산출물을 다시 만든다 — 화면 규칙까지 합쳐서. 잘못된 규칙이면 OverrideError."""
    from tap.cli import build
    return build(root / "data/specs/hmall-openapi.json", root / "data/out", root / "data/config/domains.yaml",
                 root / "data/config/services.yaml", root / "data/config/overrides.yaml",
                 rules_cfg=root / "data/config/rules.ui.yaml")


def save_rule(root: Path, rule: dict) -> dict:
    """규칙을 넣고 다시 빌드. 빌드가 실패하면 규칙 파일을 되돌린다."""
    from tap.catalog.rules import add_rule, load_rules, save_rules
    path = root / "data/config/rules.ui.yaml"
    before = load_rules(path)
    save_rules(path, add_rule(before, rule))
    try:
        return rebuild(root)
    except Exception:
        save_rules(path, before)
        raise


def delete_rule(root: Path, rid: int) -> dict:
    from tap.catalog.rules import load_rules, save_rules
    path = root / "data/config/rules.ui.yaml"
    save_rules(path, [r for r in load_rules(path) if int(r.get("id", 0)) != int(rid)])
    return rebuild(root)


def _stamp() -> tuple[str, str]:
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%Y%m%d-%H%M%S-%f")[:-3], now.strftime("%Y-%m-%d %H:%M")


def save_scenario(root: Path, body: dict) -> dict:
    """확인 후 저장 — Scenario IR 을 그대로 고정한다 (승인본). 거절된 계획 · 이름 없음은 저장하지 않는다."""
    ir, name = body.get("ir") or {}, str(body.get("name") or "").strip()
    if not name:
        raise ValueError("시나리오 이름을 적으세요")
    if ir.get("status") != "ok":
        raise ValueError("거절된 계획은 저장할 수 없습니다")
    sid, at = _stamp()
    sc = {"id": "sc-" + sid, "name": name, "utterance": body.get("utterance") or ir.get("request"), "domains": body.get("domains") or [],
          "graph_id": ir.get("graph_id"), "catalog_version": ir.get("catalog_version"), "approved_at": at, "by": "화면", "ir": ir}
    dest = root / "data/scenarios" / f"{sc['id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(sc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sc


def delete_scenario(root: Path, sid: str) -> None:
    p = root / "data/scenarios" / (re.sub(r"[^A-Za-z0-9\-]", "", sid) + ".json")
    if not p.exists():
        raise ValueError(f"없는 시나리오: {sid}")
    p.unlink()


def save_run(root: Path, body: dict) -> dict:
    """드라이런 기록 — 실행기 연결 전이라 API 를 호출하지 않고 호출 계획만 남긴다."""
    rid, at = _stamp()
    run = {"id": "run-" + rid, "at": at, "kind": "드라이런", "rows": body.get("rows") or [], "calls": body.get("calls") or [],
           "unresolved": body.get("unresolved") or [], "rollback": body.get("rollback") or []}
    dest = root / "data/runs" / f"{run['id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run


def save_baseline(root: Path, api_id: str, body: dict) -> Path:
    """Baseline Request — 실제로 성공한 요청 값 (필드 → 값). 요청 필드에 없는 이름이면 거절."""
    from datetime import datetime
    ops = json.loads((root / "data/out/api_operations.json").read_text(encoding="utf-8"))
    op = next((o for o in ops if o["api_id"] == api_id), None)
    if op is None:
        raise ValueError(f"없는 API: {api_id}")
    if not isinstance(body, dict):
        raise ValueError("전문은 {필드: 값} 객체여야 합니다")
    extra = sorted(set(body) - {f["name"] for f in op["request_fields"]})
    if extra:
        raise ValueError(f"요청 필드에 없는 이름: {', '.join(extra)}")
    dest = root / "data/baselines" / (re.sub(r"[^A-Za-z0-9]+", "_", api_id.split(":", 2)[-1]).strip("_") + ".json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"api_id": api_id, "body": body, "by": "화면", "at": datetime.now().strftime("%m-%d %H:%M")},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def make_handler(root: Path):
    proto = root / "prototype"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(proto), **kw)

        def _json(self, code: int, body) -> None:
            raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/tap-data.js":
                raw = ("window.TAP_DATA = " + json.dumps(ui_data(root), ensure_ascii=False) + ";\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if path == "/api/health":
                return self._json(200, {"ok": True})
            if path == "/":
                self.path = "/offline-ui.html"
            return super().do_GET()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            try:
                if self.path == "/api/plan":
                    from tap.cli import plan_request
                    goal = json.dumps(body["goal"], ensure_ascii=False) if body.get("goal") else None
                    r = plan_request(body["utterance"], [root / "data/knowledge", root / "data/out/graphs"], root / "data/out", goal,
                                     rules_cfg=root / "data/config/rules.ui.yaml")
                    return self._json(200, r["ir"].model_dump(mode="json"))
                if self.path == "/api/rules":
                    r = save_rule(root, body)
                    return self._json(200, {"build": r, "data": ui_data(root)})
                if self.path == "/api/rules/delete":
                    r = delete_rule(root, body["id"])
                    return self._json(200, {"build": r, "data": ui_data(root)})
                if self.path == "/api/baseline":
                    dest = save_baseline(root, body["api_id"], body["body"])
                    return self._json(200, {"file": str(dest.relative_to(root)), "data": ui_data(root)})
                if self.path == "/api/scenarios":
                    sc = save_scenario(root, body)
                    return self._json(200, {"scenario": sc, "data": ui_data(root)})
                if self.path == "/api/scenarios/delete":
                    delete_scenario(root, body["id"])
                    return self._json(200, {"data": ui_data(root)})
                if self.path == "/api/runs":
                    run = save_run(root, body)
                    return self._json(200, {"run": run, "data": ui_data(root)})
                if self.path == "/api/build":
                    before = json.loads((root / "data/out/api_catalog.json").read_text(encoding="utf-8"))
                    r = rebuild(root)
                    return self._json(200, {"build": r, "changed": r["catalog_version"] != before.get("catalog_version"), "data": ui_data(root)})
                if self.path == "/api/graph/save":
                    gid = re.sub(r"[^A-Za-z0-9_\-]", "", body["graph_id"])
                    dest = root / "data/out/graphs" / f"{gid}.yaml"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(body["yaml"], encoding="utf-8")
                    return self._json(200, {"file": str(dest.relative_to(root))})
                return self._json(404, {"error": "없는 경로"})
            except Exception as e:                              # 화면에 그대로 보여 준다
                return self._json(400 if isinstance(e, ValueError) else 500, {"error": str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"})

    return Handler


def serve(root: Path, port: int = 8765, host: str = "127.0.0.1") -> None:
    """host 기본은 이 컴퓨터에서만. WSL 밖(Windows 브라우저)에서 localhost 로 안 열리면 --host 0.0.0.0 으로 띄우고 WSL IP 로 연다."""
    httpd = ThreadingHTTPServer((host, port), make_handler(root))
    print(f"오프라인 UI → http://127.0.0.1:{port}/  (상태 그래프만: /graph-editor.html, 끝내려면 Ctrl+C)", flush=True)
    httpd.serve_forever()
