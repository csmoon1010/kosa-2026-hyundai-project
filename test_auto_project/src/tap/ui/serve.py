"""로컬 서버 — 오프라인 UI 를 띄우고, 구현된 기능은 실제로 실행한다.

    PYTHONPATH=src python -m tap.cli serve        → http://127.0.0.1:8765/offline-ui.html

  GET  /tap-data.js          산출물을 매번 새로 읽어 내려준다
  GET  /api/health           화면이 서버 모드인지 확인
  POST /api/select           {utterance} → ① 의도 분석 → ② 경로 탐색 → ③ API 선택 → 권한 등급 · 승인 게이트 (+ 트레이스)
  POST /api/approve          {selection_hash, scenario, steps, approver} → 등록 때 승인 (서버가 계산한 게이트로 확인) → 승인본 data/approved/
  POST /api/run              {selection_hash, confirm} → 실행 때 확인 (승인본 · 해시 · R2 단계 확인) → 드라이런
  POST /api/graph/save       {graph_id, yaml} → data/graphs/<id>.yaml (노드 흐름만, 기존 파일 위에 합침 — 진입 상태 · 상태 필드 · 확인 키 유지, 이전 파일은 data/out/graph_history/)
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
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

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


def save_graph(root: Path, graph_id: str, text: str) -> dict[str, Any]:
    """화면 저장 → data/graphs/<id>.yaml. 같은 그래프 파일이 있으면 그 위에 합치고, 이전 파일은 이력으로 남긴다."""
    from tap.graph.build import graph_from_dict, merge_saved
    gid = re.sub(r"[^A-Za-z0-9_\-]", "", graph_id)
    new = yaml.safe_load(text) or {}
    if (new.get("graph") or {}).get("id") != gid:
        raise ValueError(f"그래프 id 가 맞지 않습니다: {gid} ≠ {(new.get('graph') or {}).get('id')}")
    dest = root / "data/graphs" / f"{gid}.yaml"
    old_text = dest.read_text(encoding="utf-8") if dest.exists() else None
    merged, kept = merge_saved(yaml.safe_load(old_text) if old_text else None, new)
    graph_from_dict(merged)                                 # 그래프로 안 읽히는 파일은 쓰지 않는다
    backup = None
    if old_text:
        hist = root / "data/out/graph_history"
        hist.mkdir(parents=True, exist_ok=True)
        backup = hist / f"{gid}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.yaml"
        backup.write_text(old_text, encoding="utf-8")
    head = [l for l in text.splitlines() if l.startswith("#")][:2]
    if kept:
        head.append("# 기존 파일에서 유지한 그래프 칸: " + " · ".join(kept))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(head) + "\n" + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"file": str(dest.relative_to(root)), "kept": kept,
            "backup": str(backup.relative_to(root)) if backup else None}


def make_handler(root: Path, llm=None, agent_llm=None, mode: str = "agent"):
    """llm · agent_llm: 테스트에서 가짜 LLM 을 끼울 때. 없으면 .env 의 OpenAI.

    mode: ②③ 를 계획 에이전트(agent, 기본)로 할지 워크플로(workflow, 비교용)로 할지. 요청 body 의 mode 가 있으면 그것.
    """
    proto = root / "prototype"
    pending: dict[str, dict[str, Any]] = {}    # selection_hash → 서버가 계산한 선택 결과 · 게이트 (승인은 이것으로만 확인한다)

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

        def _select(self, body: dict[str, Any]) -> None:
            from tap.cli import analyze_select
            utt = str(body.get("utterance") or "").strip()
            if not utt:
                raise ValueError("자연어 요청이 비어 있습니다")
            try:
                use = body.get("mode") if body.get("mode") in ("agent", "workflow") else mode
                r = analyze_select(utt, [root / "data/graphs"], root / "data/out", root / "data/config/rules.ui.yaml",
                                   llm=llm, trace_dir=root / "data/out/traces", mode=use, agent_llm=agent_llm)
            except Exception as e:                  # 검사 거절 · 예산 초과도 트레이스와 함께 화면에 보여 준다
                tr = getattr(e, "trace", None)
                return self._json(400, {"error": f"{type(e).__name__}: {e}", "trace": tr.to_dict() if tr else None,
                                        "agent": getattr(e, "agent", None)})
            g = r["gate"]
            pending[g.selection_hash] = {"request": utt, "apis": r["apis"], "gate": g}
            return self._json(200, {"request": utt, "tasks": r["tasks"].model_dump(), "paths": r["paths"].dump(),
                                    "apis": r["apis"].dump(), "gate": g.model_dump(), "trace": r["trace"].to_dict(),
                                    "notes": r["notes"], "trace_file": str(Path(r["trace_file"]).relative_to(root)),
                                    "mode": r.get("mode", "workflow"), "agent": r.get("agent")})

        def _pending(self, body: dict[str, Any]) -> dict[str, Any]:
            p = pending.get(str(body.get("selection_hash") or ""))
            if p is None:
                raise ValueError("이 선택 결과를 서버가 모릅니다 (서버가 다시 시작됐거나 다른 결과) — 다시 분석하세요")
            return p

        def _approve(self, body: dict[str, Any]) -> None:
            """등록 때 승인 — 계획이 맞는가. 승인본을 data/approved/ 에 고정한다 (실행은 /api/run)."""
            from tap.apis.gate import GateError, approve
            p = self._pending(body)
            g = p["gate"]
            try:
                ap = approve(g, str(body.get("approver") or "화면"), bool(body.get("scenario")), list(body.get("steps") or []))
            except GateError as e:
                return self._json(400, {"error": str(e), "refused": True})
            p["approval"] = ap
            d = root / "data/approved"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{ap.selection_hash.split(':')[1][:12]}.json"
            f.write_text(json.dumps({"request": p["request"], "approval": ap.model_dump(), "gate": g.model_dump(),
                                     "selection": p["apis"].dump()}, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._json(200, {"approval": ap.model_dump(), "file": str(f.relative_to(root)), "confirm_steps": g.confirm_steps})

        def _run(self, body: dict[str, Any]) -> None:
            """실행 때 확인 — 승인본이 있는지, 그 뒤 바뀌지 않았는지, R2 단계를 이번 실행에서 확인했는지. 통과하면 드라이런."""
            from tap.apis.gate import GateError, dry_run
            p = self._pending(body)
            try:
                calls = dry_run(p["apis"], p["gate"], p.get("approval"), list(body.get("confirm") or []))
            except GateError as e:
                return self._json(400, {"error": str(e), "refused": True})
            return self._json(200, {"calls": calls, "confirmed": list(body.get("confirm") or []),
                                    "approval": p["approval"].model_dump() if p.get("approval") else None})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            try:
                if self.path == "/api/select":
                    return self._select(body)
                if self.path == "/api/approve":
                    return self._approve(body)
                if self.path == "/api/run":
                    return self._run(body)
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
                    return self._json(200, save_graph(root, body["graph_id"], body["yaml"]))
                return self._json(404, {"error": "없는 경로"})
            except Exception as e:                              # 화면에 그대로 보여 준다
                return self._json(400 if isinstance(e, ValueError) else 500, {"error": str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"})

    return Handler


def serve(root: Path, port: int = 8765, host: str = "127.0.0.1") -> None:
    """host 기본은 이 컴퓨터에서만. WSL 밖(Windows 브라우저)에서 localhost 로 안 열리면 --host 0.0.0.0 으로 띄우고 WSL IP 로 연다."""
    httpd = ThreadingHTTPServer((host, port), make_handler(root))
    print(f"오프라인 UI → http://127.0.0.1:{port}/  (상태 그래프만: /graph-editor.html, 끝내려면 Ctrl+C)", flush=True)
    httpd.serve_forever()
