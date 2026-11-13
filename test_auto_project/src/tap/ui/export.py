"""화면 데이터 — data/out · data/graphs · data/registered · data/runs 를 window.TAP_DATA 한 덩어리로 (GET /tap-data.js).

화면은 이 값으로 API 문서 · 상태 그래프 · 검수 목록 · 보정 규칙 · Baseline · 전처리 산출물(data/out/parameters) ·
등록 시나리오 목록(요약) · 실행 이력을 그린다. 값이 없으면(서버 없이 HTML 만 열면) 시연 데이터를 쓴다.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from functools import cache
from typing import Any, Callable, Iterable

import yaml

from tap.catalog.build import load_overrides
from tap.catalog.rules import load_rules
from tap.ui.preprocessing import legacy_baselines, load_preprocessing


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


def _code_groups(path: Path) -> list[dict[str, Any]]:
    """공통코드 테이블 export 전체 — 그룹별 (사용여부 Y, 정렬순서대로). '새 그래프' 에서 고른다."""
    if not path.exists():
        return []
    from tap.graph.build import load_code_table
    with open(path, encoding="utf-8", newline="") as f:
        ids = list(dict.fromkeys(r["코드그룹ID"] for r in csv.DictReader(f)))
    out = [load_code_table(path, g) for g in ids]
    for g in out:                                   # JS 객체는 '00' 같은 키 순서를 바꾸므로 정렬순서를 따로 싣는다
        g["order"] = list(g["codes"])
    return out


def ui_parts(root: Path) -> dict[str, Callable[[], Any]]:
    """화면 데이터의 칸마다 만드는 함수 — 필요한 칸만 만든다 (관리자 화면이 칸을 나눠 받는다, docs/react.md 6절).
    같은 파일은 한 번만 읽는다. 모든 칸을 만든 결과가 ui_data()."""
    out = root / "data/out"
    meta = cache(lambda: _load(out / "api_metadata.json", []))
    ops = cache(lambda: _load(out / "api_operations.json", []))
    reg = cache(lambda: _load(out / "tool_registry.json", {"connections": [], "tools": []}))
    cat = cache(lambda: _load(out / "api_catalog.json", {}))
    review = cache(lambda: _load(out / "review_queue.json", []))
    graphs = cache(lambda: [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((root / "data/graphs").glob("*.yaml"))])
    preprocessing = cache(lambda: load_preprocessing(root))

    def build() -> dict[str, Any]:
        kinds, doms = {}, {}
        for m in meta():
            kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
            doms[m["domain"]] = doms.get(m["domain"], 0) + 1
        return {"operations": len(ops()), "catalog_version": cat().get("catalog_version"),
                "spec_sources": cat().get("spec_sources") or [], "kinds": kinds, "domains": doms, "review": len(review())}

    def digests() -> list[dict[str, Any]]:
        by = {m["api_id"]: m for m in meta()}
        return [_digest(o, by[o["api_id"]]) for o in ops() if o["api_id"] in by]

    tool_keys = ("api_id", "domain", "method", "endpoint", "body_format", "base_url", "timeout_ms", "retry_count",
                 "approval_required", "auth_type", "auth_profile", "enabled", "success_rule")
    return {
        "generated_at": lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "build": build,
        "catalog": lambda: cat().get("apis") or [],
        "metadata": meta,
        "ops": digests,
        "tools": lambda: [{k: t.get(k) for k in tool_keys} for t in reg()["tools"]],
        "connections": lambda: reg()["connections"],
        "review": review,
        "graphs": graphs,
        "codes": lambda: _code_groups(root / "data/codes/common_codes.csv"),
        "rules": lambda: load_rules(root / "data/config/rules.ui.yaml"),
        "overrides_file": lambda: load_overrides(root / "data/config/overrides.yaml"),
        "preprocessing": preprocessing,
        "baselines": lambda: {**{b["api_id"]: b for b in (_load(p) for p in sorted((root / "data/baselines").glob("*.json"))) if b},
                              **legacy_baselines(preprocessing())},
        "runs": lambda: runs_list(root),
        # 최종 등록 화면에서 승인 · 등록한 시나리오 (2026-11-12) — 예전 형식(scenarios)과 따로 둔다. 화면 목록엔 요약만
        "registered": lambda: registered_list(root),
        "drafts": lambda: [g for g in graphs() if "layout" in g],     # 화면에서 한 번이라도 저장한 그래프 (배치 · 승인본 번호가 있음)
    }


def ui_part(root: Path, keys: Iterable[str]) -> dict[str, Any]:
    """화면 데이터 중 keys 칸만."""
    parts = ui_parts(root)
    return {k: parts[k]() for k in keys}


def ui_data(root: Path) -> dict[str, Any]:
    return {k: make() for k, make in ui_parts(root).items()}


def runs_list(root: Path) -> list[dict[str, Any]]:
    """실행 이력 — 최신순. 화면 데이터 전체를 만들지 않고 이것만 (실행 이력 API)."""
    return [x for x in (_load(p) for p in sorted((root / "data/runs").glob("*.json"), reverse=True)) if x]


def registered_list(root: Path) -> list[dict[str, Any]]:
    """등록 시나리오 목록(요약) — 최신순. 화면 데이터 전체를 만들지 않고 이것만 (등록 목록 API)."""
    return [registered_summary(x) for x in (_load(p) for p in sorted((root / "data/registered").glob("*.json"), reverse=True)) if x]


def registered_summary(rec: dict[str, Any]) -> dict[str, Any]:
    """등록 시나리오 목록 한 줄 — 이름 · 요청 · 도메인 · 단계 수 · 되돌릴 수 없는 단계 수 · 등록 시각 · 카탈로그 버전."""
    steps = (rec.get("gate") or {}).get("steps") or []
    return {"id": rec.get("id"), "name": rec.get("name"), "utterance": rec.get("utterance"), "domains": rec.get("domains") or [],
            "registered_at": rec.get("registered_at"), "catalog_version": rec.get("catalog_version"),
            "approver": (rec.get("approval") or {}).get("approver"),
            "steps": len(steps), "irreversible": sum(1 for s in steps if s.get("tier") == "R2"),
            # 실행 메뉴 — 되돌릴 수 없는 단계는 실행할 때마다 확인 (key 는 서버 확인용, 이름은 화면용)
            "confirm_steps": [{"key": s.get("key"), "edge": s.get("edge")} for s in steps if s.get("confirm_on_run")]}


def write_ui_data(root: Path, dest: Path) -> Path:
    dest.write_text("/* tap.cli ui-data 로 생성 — 손으로 고치지 않는다 */\nwindow.TAP_DATA = "
                    + json.dumps(ui_data(root), ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    return dest
