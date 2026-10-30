"""오프라인 UI 에 실제 산출물을 입힌다 — data/out · data/graphs 를 window.TAP_DATA 한 덩어리로.

화면은 이 값이 있으면 구현된 영역(데이터 조회 · 상태 그래프 · 시나리오 생성 결과 · 검수 목록)을 실제 산출물로 그리고,
없으면 예전처럼 시연 데이터를 쓴다. 실행 · 이력 · Baseline · Parameter KB 는 아직 시연 데이터.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tap.catalog.build import load_overrides
from tap.catalog.rules import load_rules


def _load(p: Path, default: Any = None) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _digest(o: dict[str, Any], m: dict[str, Any]) -> dict[str, Any]:
    def fl(fs):
        seen, out = set(), []
        for f in fs:
            if f["name"] in seen:
                continue
            seen.add(f["name"])
            out.append([f["name"], f.get("label") if f.get("label") != f["name"] else "", str(f.get("example") or "")[:24]])
        return out
    return {"id": o["api_id"], "path": o["path"], "sum": o["summary"], "kind": m["kind"], "dom": m["domain"],
            "req": fl(o["request_fields"]), "res": fl(o["response_fields"])}


def _ai(out: Path, graph_id: str) -> dict[str, Any] | None:
    """그래프 재료 추출(실험) 결과 — gpt-5.5 를 먼저, 없으면 아무거나 하나."""
    files = sorted((out / "extract").glob(f"{graph_id}.*.yaml"), key=lambda p: ("gpt-5.5" not in p.name, p.name))
    if not files:
        return None
    k = yaml.safe_load(files[0].read_text(encoding="utf-8"))
    model = files[0].name[len(graph_id) + 1:].rsplit(".", 2)[0]
    return {"model": model, "file": files[0].name, "transitions": k.get("transitions") or [],
            "lookups": k.get("lookups") or [], "state_field": k["graph"].get("state_field"),
            "questions": k.get("open_questions") or []}


def _code_groups(path: Path) -> list[dict[str, Any]]:
    """공통코드 테이블 export 전체 — 그룹별 (사용여부 Y, 정렬순서대로). '새 그래프' 에서 고른다."""
    if not path.exists():
        return []
    from tap.graph.extract import load_code_table
    with open(path, encoding="utf-8", newline="") as f:
        ids = list(dict.fromkeys(r["코드그룹ID"] for r in csv.DictReader(f)))
    out = [load_code_table(path, g) for g in ids]
    for g in out:                                   # JS 객체는 '00' 같은 키 순서를 바꾸므로 정렬순서를 따로 싣는다
        g["order"] = list(g["codes"])
    return out


def ui_data(root: Path) -> dict[str, Any]:
    out = root / "data/out"
    meta = _load(out / "api_metadata.json", [])
    ops = _load(out / "api_operations.json", [])
    reg = _load(out / "tool_registry.json", {"connections": [], "tools": []})
    cat = _load(out / "api_catalog.json", {})
    review = _load(out / "review_queue.json", [])
    by = {m["api_id"]: m for m in meta}
    graphs = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((root / "data/graphs").glob("*.yaml"))]
    kinds, doms = {}, {}
    for m in meta:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
        doms[m["domain"]] = doms.get(m["domain"], 0) + 1
    tool_keys = ("api_id", "domain", "method", "endpoint", "body_format", "base_url", "timeout_ms", "retry_count",
                 "approval_required", "auth_type", "auth_profile", "enabled", "success_rule")
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "build": {"operations": len(ops), "catalog_version": cat.get("catalog_version"),
                  "spec_sources": cat.get("spec_sources") or [], "kinds": kinds, "domains": doms,
                  "review": len(review)},
        "catalog": cat.get("apis") or [],
        "metadata": meta,
        "ops": [_digest(o, by[o["api_id"]]) for o in ops if o["api_id"] in by],
        "tools": [{k: t.get(k) for k in tool_keys} for t in reg["tools"]],
        "connections": reg["connections"],
        "review": review,
        "graphs": graphs,
        "codes": _code_groups(root / "data/codes/common_codes.csv"),
        "rules": load_rules(root / "data/config/rules.ui.yaml"),
        "overrides_file": load_overrides(root / "data/config/overrides.yaml"),
        "baselines": {b["api_id"]: b for b in (_load(p) for p in sorted((root / "data/baselines").glob("*.json"))) if b},
        "scenarios": [x for x in (_load(p) for p in sorted((root / "data/scenarios").glob("*.json"), reverse=True)) if x],
        "runs": [x for x in (_load(p) for p in sorted((root / "data/runs").glob("*.json"), reverse=True)) if x],
        "drafts": [g for g in graphs if "layout" in g],     # 화면에서 한 번이라도 저장한 그래프 (배치 · 승인본 번호가 있음)
        "ai": {gid: _ai(out, gid) for gid in dict.fromkeys([g["graph"]["id"] for g in graphs]
                                                           + [c["id"] for c in _code_groups(root / "data/codes/common_codes.csv")])},
        "irs": [_load(p) for p in sorted((out / "ir").glob("*.json"))],
    }


def write_ui_data(root: Path, dest: Path) -> Path:
    dest.write_text("/* tap.cli ui-data 로 생성 — 손으로 고치지 않는다 */\nwindow.TAP_DATA = "
                    + json.dumps(ui_data(root), ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    return dest
