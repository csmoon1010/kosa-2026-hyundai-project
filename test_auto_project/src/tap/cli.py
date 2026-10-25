"""1단계 사전 작업 실행기.

    PYTHONPATH=src python -m tap.cli build --spec data/specs/hmall-openapi.json

산출물 (data/out/) — 세 문서는 모두 api_id 로 연결된다
    api_operations.json   파싱 결과 — 혜정의 Canonical Schema 변환 입력
    tool_registry.json    Tool Registry (도메인별 연결 설정 + API별 도구, PK = api_id)
    api_metadata.json     API Metadata (Catalog 의 원본, tool_enabled 는 Tool Registry 에서 복사)
    api_catalog.json      API Catalog (Metadata 에서 복사, 내용이 바뀔 때만 버전 증가)
    review_queue.json     규칙으로 확정하지 못한 항목

생성 순서: 파싱 → 도메인 · 쓰기/조회 분류 → Tool Registry → Metadata → Catalog
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from pydantic import BaseModel

from tap.catalog.build import (build_catalog, build_metadata, classify_domain, classify_kind, file_hash,
                               load_domain_rules, load_overrides, validate_overrides)
from tap.models import SpecSource
from tap.registry.tools import build_tool_registry, load_services, service_name
from tap.spec.parser import base_url, load_spec, parse_operations

ROOT = Path(__file__).resolve().parents[2]


def _dump(path: Path, data) -> None:
    def conv(x):
        if isinstance(x, BaseModel):
            return x.model_dump(mode="json")
        if isinstance(x, list):
            return [conv(i) for i in x]
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        return x
    path.write_text(json.dumps(conv(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build(spec_path: Path, out_dir: Path, domains_cfg: Path, services_cfg: Path,
          overrides_cfg: Path | None = None, now: str | None = None) -> dict:
    services = load_services(services_cfg)
    overrides = load_overrides(overrides_cfg) if overrides_cfg else {}
    spec = load_spec(spec_path)
    service = service_name(spec_path.name, services)
    spec_hash = file_hash(spec_path)

    ops = parse_operations(spec, spec_path.name, service)
    validate_overrides(overrides, {o.api_id for o in ops})       # 모르는 키 · 잘못된 값 → 빌드 실패
    rules = load_domain_rules(domains_cfg)
    guesses = {o.api_id: classify_domain(o, rules) for o in ops}
    kinds = {o.api_id: classify_kind(o)[0] for o in ops}

    conns, tools = build_tool_registry(ops, {k: g.domain for k, g in guesses.items()}, kinds, spec_hash,
                                       services, base_url(spec), overrides)
    prev_meta = {m["api_id"]: m for m in (_load(out_dir / "api_metadata.json") or [])}
    meta, review = build_metadata(ops, guesses, {t.api_id: t.enabled for t in tools},
                                  {spec_path.name: spec_hash}, overrides, prev_meta)
    catalog = build_catalog(meta, [SpecSource(service=service, document_id=spec_path.name, spec_hash=spec_hash)],
                            _load(out_dir / "api_catalog.json"), now)
    review += [{"api_id": t.api_id, "item": "success_rule", "reason": "성공 응답 구조에서 규칙을 찾지 못함"}
               for t in tools if t.success_rule is None]
    review += [{"api_id": t.api_id, "item": "enabled", "reason": "인증 비밀값 참조(auth_profile) 없음"}
               for t in tools if not t.enabled and "enabled" not in overrides.get(t.api_id, {})]

    out_dir.mkdir(parents=True, exist_ok=True)
    _dump(out_dir / "api_operations.json", ops)
    _dump(out_dir / "tool_registry.json", {"connections": conns, "tools": tools})
    _dump(out_dir / "api_metadata.json", meta)
    _dump(out_dir / "api_catalog.json", catalog)
    _dump(out_dir / "review_queue.json", review)

    return {
        "operations": len(ops),
        "catalog_version": catalog.catalog_version,
        "domains": dict(collections.Counter(m.domain for m in meta)),
        "kinds": dict(collections.Counter(m.kind for m in meta)),
        "success_rule": dict(collections.Counter(
            (t.success_rule or {}).get("equals", "없음") for t in tools)),
        "review": dict(collections.Counter(r["item"] for r in review)),
        "connections": {c.domain: f"{c.base_url or c.base_url_default} · {c.timeout_ms}ms ({c.source})"
                        for c in conns},
    }


def plan_request(utterance: str, knowledge: Path, out_dir: Path, goal_json: str | None = None,
                 model: str | None = None) -> dict:
    """자연어 한 문장 → 목표 → 경로 → Scenario IR. data/out/ 의 1단계 산출물을 쓴다."""
    import hashlib

    from tap.goal.extract import extract_goal, openai_parse
    from tap.graph.build import load_knowledge, validate_graph
    from tap.graph.plan import Goal, plan
    from tap.ir.build import build_ir

    ops = _load(out_dir / "api_operations.json")
    meta = _load(out_dir / "api_metadata.json")
    cat = _load(out_dir / "api_catalog.json") or {}
    if ops is None or meta is None:
        raise SystemExit("data/out 산출물이 없습니다 — 먼저 build 를 실행하세요")
    graph = load_knowledge(knowledge)
    errors = [i for i in validate_graph(graph, meta, ops) if i["level"] == "error"]
    if errors:
        raise SystemExit(f"그래프 오류: {errors}")

    goal = Goal.model_validate_json(goal_json) if goal_json else extract_goal(utterance, graph, openai_parse(model))
    ir = build_ir(utterance, goal, graph, plan(graph, goal), ops, meta, cat.get("catalog_version"))
    ir_dir = out_dir / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(utterance.encode("utf-8")).hexdigest()[:8]
    _dump(ir_dir / f"{name}.json", ir)
    return {"file": str(ir_dir / f"{name}.json"), "ir": ir}


def _print_ir(ir) -> None:
    g = ir.goal
    print(f"\n▶ {ir.request}")
    print(f"  목표: target={g.target} must_pass={g.must_pass} count={g.count}  근거={g.source_phrases}"
          + (f"  표현 못한 조건={g.unsupported}" if g.unsupported else ""))
    if ir.status != "ok":
        print(f"  ✕ 거절: {ir.reason}")
        return
    p = ir.plan
    print(f"  A {p.strategy}: 시작 {p.start} · 쓰기 {p.writes}회 · 상태 {' → '.join(p.states)}")
    for s in ir.steps:
        extra = f" 되돌리기={s.compensate_with.rsplit(':', 1)[-1]}" if s.compensate_with else ""
        print(f"    {s.no}. [{s.kind}] {s.name} {s.selector or ''}{extra}")
    if ir.alternative:
        a = ir.alternative
        print(f"  B 대안 {a.strategy}: 시작 {a.start} · 쓰기 {a.writes}회 · 상태 {' → '.join(a.states)}")
    print(f"  실행 시 입력: {list(ir.run_inputs)} · 미해결 {len(ir.unresolved)}개 · 승인 필요={ir.requires_approval}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="tap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="명세 → Tool Registry · API Metadata · API Catalog")
    b.add_argument("--spec", default=str(ROOT / "data/specs/hmall-openapi.json"))
    b.add_argument("--out", default=str(ROOT / "data/out"))
    b.add_argument("--domains", default=str(ROOT / "data/config/domains.yaml"))
    b.add_argument("--services", default=str(ROOT / "data/config/services.yaml"))
    b.add_argument("--overrides", default=str(ROOT / "data/config/overrides.yaml"))
    pl = sub.add_parser("plan", help="자연어 → 목표 → 경로 → Scenario IR")
    pl.add_argument("utterance", nargs="+", help="자연어 요청 (여러 개 가능)")
    pl.add_argument("--knowledge", default=str(ROOT / "data/knowledge/ord_stat.yaml"))
    pl.add_argument("--out", default=str(ROOT / "data/out"))
    pl.add_argument("--goal", default=None, help="LLM 없이 목표 JSON 을 직접 지정")
    pl.add_argument("--model", default=None)
    a = ap.parse_args()
    if a.cmd == "plan":
        for u in a.utterance:
            r = plan_request(u, Path(a.knowledge), Path(a.out), a.goal, a.model)
            _print_ir(r["ir"])
            print(f"  → {r['file']}")
        return
    if a.cmd == "build":
        r = build(Path(a.spec), Path(a.out), Path(a.domains), Path(a.services), Path(a.overrides))
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
