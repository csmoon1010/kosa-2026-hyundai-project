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
from typing import Any

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
          overrides_cfg: Path | None = None, now: str | None = None, rules_cfg: Path | None = None,
          permissions_cfg: Path | None = None) -> dict:
    """rules_cfg: 화면에서 넣은 규칙(rules.ui.yaml) — Catalog · MetaData 항목을 overrides 위에 합친다."""
    from tap.catalog.rules import load_rules, merge_overrides, rule_overrides

    services = load_services(services_cfg)
    overrides = load_overrides(overrides_cfg) if overrides_cfg else {}
    overrides = merge_overrides(overrides, rule_overrides(load_rules(rules_cfg)))
    spec = load_spec(spec_path)
    service = service_name(spec_path.name, services)
    spec_hash = file_hash(spec_path)

    ops = parse_operations(spec, spec_path.name, service)
    validate_overrides(overrides, {o.api_id for o in ops},       # 모르는 키 · 잘못된 값 → 빌드 실패
                       {o.api_id: {f.name for f in o.request_fields} for o in ops})
    rules = load_domain_rules(domains_cfg)
    guesses = {o.api_id: classify_domain(o, rules) for o in ops}
    kinds = {o.api_id: classify_kind(o)[0] for o in ops}

    from tap.apis.gate import load_permissions
    perms = load_permissions(permissions_cfg or ROOT / "data/config/permissions.yaml")
    conns, tools = build_tool_registry(ops, {k: g.domain for k, g in guesses.items()}, kinds, spec_hash,
                                       services, base_url(spec), overrides, perms)
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


GRAPH_DIR = ROOT / "data/graphs"        # 상태 그래프는 여기 한 곳 — 손으로 쓴 것 · 화면에서 그린 것 모두 <코드그룹ID>.yaml
GOLDEN = ROOT / "data/golden/ORD_STAT_GBCD.yaml"   # 채점 · 테스트용 정답지 (고정 복사본)


def _apply_synonyms(graphs, rules_cfg: Path | None) -> None:
    """화면에서 넣은 State Vocabulary 동의어 → 그래프 고르기 · 목표 추출 · 의도 분석에 보여 준다."""
    if not rules_cfg:
        return
    from tap.catalog.rules import load_rules, synonyms_of
    rules = load_rules(rules_cfg)
    for g in graphs:
        for code, words in synonyms_of(rules, g.graph_id).items():
            n = next((x for x in g.nodes if x.code == code), None)
            if n:
                n.synonyms = words


LLM_CFG = ROOT / "data/config/llm.yaml"      # 요청당 예산 · 모델 가격


def _graphs(graph_dirs: list[Path] | None, rules_cfg: Path | None, out_dir: Path | None = None):
    """경로 탐색 · API 선택에 쓰는 그래프 — API 없는 화살표도 남긴다 (API 선택이 '보류'로 알린다).

    조회 방법이 적혀 있지 않은 그래프(화면에서 그린 것)는 '조회로 찾을 수 있는 상태'를 지금 매칭기로 정한다.
    """
    from tap.graph.build import load_graphs
    from tap.graph.match import attach_lookups
    graphs, _ = load_graphs(graph_dirs or [GRAPH_DIR], keep_unmatched=True)
    _apply_synonyms(graphs, rules_cfg)
    out_dir = out_dir or ROOT / "data/out"
    meta, ops = _load(out_dir / "api_metadata.json"), _load(out_dir / "api_operations.json")
    if meta is not None and ops is not None:
        attach_lookups(graphs, meta, ops, ["pd", "od", "ds"])
    return graphs


def _traced(utterance: str, model: str | None, llm, trace):
    """트레이스(없으면 새로) + 트레이스로 감싼 LLM. 실제 OpenAI 는 SDK 재시도를 끄고 트레이스가 재시도 · 예산을 맡는다."""
    from tap.goal.extract import openai_parse
    from tap.trace import Trace, load_llm_config
    if trace is None:
        budget, pricing = load_llm_config(LLM_CFG)
        trace = Trace(utterance, budget, pricing)
    return trace, trace.wrap(llm or openai_parse(model, sdk_retries=0, max_output_tokens=trace.budget.max_output_tokens))


def analyze_intent(utterance: str, domains_cfg: Path | None = None, model: str | None = None, llm=None, trace=None) -> dict:
    """자연어 한 문장 → 업무 목록(TaskPlan). 업무 도메인 목록만 LLM 에 준다 (그래프는 경로 탐색 단계가 본다)."""
    from tap.catalog.build import load_domain_rules
    from tap.goal.extract import extract_tasks

    trace, llm = _traced(utterance, model, llm, trace)
    domains = load_domain_rules(domains_cfg or ROOT / "data/config/domains.yaml")["domains"]
    with trace.span("① 의도 분석"):
        plan_, notes = extract_tasks(utterance, domains, llm)
    return {"plan": plan_, "notes": notes, "trace": trace}


def analyze_paths(utterance: str, graph_dirs: list[Path] | None = None, domains_cfg: Path | None = None,
                  rules_cfg: Path | None = None, model: str | None = None, llm=None, tasks_json: str | None = None,
                  trace=None, out_dir: Path | None = None) -> dict:
    """자연어 → 업무 목록 → 업무마다 그래프 · 출발 · 목표 상태 · 경로. tasks_json 을 주면 업무 의도 분석(LLM)을 건너뛴다."""
    from tap.goal.extract import TaskPlan
    from tap.graph.paths import find_paths

    trace, wrapped = _traced(utterance, model, llm, trace)
    if tasks_json:
        tp, notes = TaskPlan.model_validate_json(tasks_json), []
    else:
        r = analyze_intent(utterance, domains_cfg, llm=wrapped, trace=_NoWrap(trace))
        tp, notes = r["plan"], r["notes"]
    graphs = _graphs(graph_dirs, rules_cfg, out_dir)
    with trace.span("② 경로 탐색"):
        pp, pnotes = find_paths(tp, graphs, wrapped)
    return {"tasks": tp, "paths": pp, "notes": notes + pnotes, "trace": trace}


class _NoWrap:
    """이미 감싼 LLM 을 넘길 때 — 같은 트레이스에 단계(span)만 더하고 두 번 감싸지 않는다."""

    def __init__(self, trace):
        self._t = trace

    def wrap(self, llm):
        return llm

    def __getattr__(self, name):
        return getattr(self._t, name)


def analyze_select(utterance: str, graph_dirs: list[Path] | None = None, out_dir: Path | None = None,
                   rules_cfg: Path | None = None, model: str | None = None, llm=None, tasks_json: str | None = None,
                   trace=None, trace_dir: Path | None = None, stop_retry: bool = True) -> dict:
    """자연어 → 업무 목록 → 경로 → 단계마다 API. 1단계 산출물(Catalog · Metadata · operations)을 쓴다.

    트레이스(호출별 단계 · 토큰 · 지연 · 비용, 단계별 시간)는 끝나면(예산 초과로 멈춰도) trace_dir 에 남긴다.
    stop_retry: '중지조건 · 재시도' 토글 — 끄면 재시도 0회 (혜정 IR 생성의 같은 옵션과 함께 켜고 끈다, 발표 비교용).
    """
    from tap.apis.select import select_apis
    from tap.goal.extract import GoalError
    from tap.trace import Stopped

    out_dir = out_dir or ROOT / "data/out"
    ops, meta, cat = _load(out_dir / "api_operations.json"), _load(out_dir / "api_metadata.json"), _load(out_dir / "api_catalog.json")
    if ops is None or meta is None or cat is None:
        raise SystemExit("data/out 산출물이 없습니다 — 먼저 build 를 실행하세요")
    trace, wrapped = _traced(utterance, model, llm, trace)
    if not stop_retry:
        trace.budget.retries = 0
    trace.options = {"stop_retry": stop_retry}
    result: dict[str, Any] = {"trace": trace}
    try:
        from tap.apis.gate import blocked_gate, detect_injections, gate_for, load_permissions, system_identifiers
        from tap.apis.select import ApiSelection, Unresolved
        from tap.goal.extract import TaskPlan
        from tap.graph.paths import PathPlan
        perms = load_permissions(ROOT / "data/config/permissions.yaml")
        if tasks_json:
            tp, notes = TaskPlan.model_validate_json(tasks_json), []
        else:
            ri = analyze_intent(utterance, llm=wrapped, trace=_NoWrap(trace))
            tp, notes = ri["plan"], ri["notes"]
        graphs = _graphs(graph_dirs, rules_cfg, out_dir)
        hits = detect_injections(utterance, tp.injections, perms, system_identifiers(meta, graphs))
        if hits:                                # 요청 속 지시문 — ② ③ 을 하지 않고 요청 전체를 차단
            pp = PathPlan(original_question=utterance, paths=[], unresolved=list(tp.unresolved))
            sel = ApiSelection(original_question=utterance, status="차단", api_selection_results=[],
                               unresolved=[Unresolved(path_sequence=None, step=None, reason=f"요청 속 지시문 감지 — 전체 차단 ({h})") for h in hits])
            trace.finish("차단 (인젝션) [INJECTION_BLOCKED]")
            result.update(tasks=tp, paths=pp, apis=sel, gate=blocked_gate(sel, hits), trace=trace, notes=notes, injections=hits)
            return result
        r = analyze_paths(utterance, graph_dirs, rules_cfg=rules_cfg, llm=wrapped, trace=_NoWrap(trace),
                          tasks_json=tp.model_dump_json(), out_dir=out_dir)
        r["notes"] = notes + r["notes"]
        with trace.span("③ API 선택"):
            sel = select_apis(r["tasks"], r["paths"], graphs, meta, ops, cat, wrapped)
        gate = gate_for(sel, r["paths"], graphs, meta, perms)
        trace.finish(sel.status)
        result.update(r, apis=sel, gate=gate, trace=trace, injections=[])
    except Stopped as e:                        # 예산 · LLM 거절 · 출력 토큰 한도 · 재시도 대기 — 정지조건
        trace.finish(trace.status if trace.status.startswith("중단") else f"중단: {e}")
        e.trace = trace                         # 멈춘 요청도 트레이스로 채점 · 보고할 수 있게
        raise
    except GoalError as e:                      # 받은 뒤 검사(근거 구절 · 상태 소속 등)가 거절 — 다시 묻지 않음
        trace.finish(f"중단: 검사 거절 — {str(e)[:160]} [CHECK_REJECTED]")
        e.trace = trace
        raise
    except Exception as e:
        trace.finish(f"실패: {type(e).__name__}: {str(e)[:160]} [LLM_STOPPED]")
        e.trace = trace
        raise
    finally:
        result["trace_file"] = str(trace.save(trace_dir or out_dir / "traces"))
    return result


def plan_request(utterance: str, graphs_from: Path | list[Path], out_dir: Path, goal_json: str | None = None,
                 model: str | None = None, rules_cfg: Path | None = None) -> dict:
    """자연어 한 문장 → (그래프 고르기) → 목표 → 경로 → Scenario IR. data/out/ 의 1단계 산출물을 쓴다.

    graphs_from: 그래프 yaml 하나 또는 폴더 목록 (보통 [GRAPH_DIR]). 그래프가 여럿이면 LLM 이 요청에 맞는 그래프를 먼저 고른다.
    """
    import hashlib

    from tap.goal.extract import choose_graph, extract_goal, openai_parse
    from tap.graph.build import load_graphs, validate_graph
    from tap.graph.plan import Goal, plan
    from tap.ir.build import ScenarioIR, build_ir

    ops = _load(out_dir / "api_operations.json")
    meta = _load(out_dir / "api_metadata.json")
    cat = _load(out_dir / "api_catalog.json") or {}
    if ops is None or meta is None:
        raise SystemExit("data/out 산출물이 없습니다 — 먼저 build 를 실행하세요")
    graphs, _notes = load_graphs(graphs_from if isinstance(graphs_from, (list, tuple)) else [graphs_from])
    if not graphs:
        raise ValueError("시나리오 생성에 쓸 상태 그래프가 없습니다")
    _apply_synonyms(graphs, rules_cfg)

    if goal_json:
        goal = Goal.model_validate_json(goal_json)
        graph, why = next((g for g in graphs if g.graph_id == goal.graph_id), graphs[0]), "목표를 직접 지정"
    else:
        llm = openai_parse(model)
        graph, why = choose_graph(utterance, graphs, llm)
        goal = extract_goal(utterance, graph, llm) if graph else None
    if graph is None:
        ir = ScenarioIR(status="rejected", request=utterance, goal=Goal(graph_id="-", target="-"), graph_id="-",
                        catalog_version=cat.get("catalog_version"), reason=f"요청에 맞는 상태 그래프가 없습니다 — {why}", graph_reason=why)
    else:
        errors = [i for i in validate_graph(graph, meta, ops) if i["level"] == "error"]
        if errors:
            raise ValueError(f"그래프 {graph.graph_id} 오류: {errors}")
        ir = build_ir(utterance, goal, graph, plan(graph, goal), ops, meta, cat.get("catalog_version"))
        ir.graph_reason = why
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


# 한 바퀴 때 쓴 목표 4개 — 추출한 그래프로도 같은 경로가 나오는지 본다
LOOP_GOALS = [dict(target="45"), dict(target="45", must_pass=["50"]), dict(target="50", count=2), dict(target="20")]


def extract_graph(codes_csv: Path, group: str, golden: Path | None, out_dir: Path,
                  model: str | None = None, tag: str = "1", domain: str = "od") -> dict:
    """공통코드 + 명세만으로 그래프 재료 추출 → 정답지와 채점. data/out/extract/ 에 저장."""
    import os

    import yaml

    from tap.goal.extract import openai_parse
    from tap.graph.extract import extract_knowledge, load_code_table
    from tap.graph.plan import Goal
    from tap.graph.score import score

    ops, meta = _load(out_dir / "api_operations.json"), _load(out_dir / "api_metadata.json")
    if ops is None or meta is None:
        raise SystemExit("data/out 산출물이 없습니다 — 먼저 build 를 실행하세요")
    cg = load_code_table(codes_csv, group)
    got = extract_knowledge(cg, ops, meta, openai_parse(model), domain)
    used = model or os.environ.get("OPENAI_DEFAULT_MODEL", "llm")

    ex_dir = out_dir / "extract"
    ex_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{group}.{used}.{tag}"               # 모델명에 점이 있어 with_suffix 를 쓰지 않는다
    (ex_dir / f"{stem}.yaml").write_text(
        f"# 자동 추출 (실험) — 공통코드 + 명세만, 모델 {used}. 사람 확인 전\n"
        + yaml.safe_dump(got, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = {"model": used, "file": str(ex_dir / f"{stem}.yaml"), "knowledge": got}
    if golden:
        gold = yaml.safe_load(golden.read_text(encoding="utf-8"))
        result["score"] = score(gold, got, [Goal(graph_id=group, **g) for g in LOOP_GOALS])
        _dump(ex_dir / f"{stem}.score.json", result["score"])
    return result


def rescore(files: list[Path], group: str, golden: Path) -> list[dict]:
    """이미 추출해 둔 yaml 을 LLM 없이 다시 채점 (채점 규칙을 고쳤을 때 · 사람이 고친 뒤)."""
    import yaml

    from tap.graph.plan import Goal
    from tap.graph.score import score

    gold = yaml.safe_load(golden.read_text(encoding="utf-8"))
    out = []
    for f in files:
        got = yaml.safe_load(f.read_text(encoding="utf-8"))
        r = {"model": f.name.split(".", 1)[1].rsplit(".", 1)[0], "file": str(f), "knowledge": got,
             "score": score(gold, got, [Goal(graph_id=group, **g) for g in LOOP_GOALS])}
        _dump(f.with_name(f.name[: -len(".yaml")] + ".score.json"), r["score"])
        out.append(r)
    return out


def match_graph(golden: Path, out_dir: Path, domains: list[str]) -> dict:
    """정답 그래프의 화살표 이름 · 상태만 주고 API 후보를 찾아 채점. data/out/match/ 에 저장."""
    import yaml

    from tap.graph.match import evaluate

    ops, meta = _load(out_dir / "api_operations.json"), _load(out_dir / "api_metadata.json")
    if ops is None or meta is None:
        raise SystemExit("data/out 산출물이 없습니다 — 먼저 build 를 실행하세요")
    gold = yaml.safe_load(golden.read_text(encoding="utf-8"))
    r = evaluate(gold, meta, ops, domains)
    (out_dir / "match").mkdir(parents=True, exist_ok=True)
    _dump(out_dir / "match" / f"{gold['graph']['id']}.json", r)
    return r


def _print_score(r: dict) -> None:
    s = r["score"]
    print(f"\n■ {r['model']} → {r['file']}")
    for name, rows in (("전이", s["transitions"]), ("조회 방법", s["lookups"])):
        c = s["summary"]["transitions" if name == "전이" else "lookups"]
        print(f"  {name}: 정답 {c['정답']}개 중 정확 {c['정확']} · 틀림 {c['틀림']} · 없음 {c['없음']} · 정답에 없는 추가 {c['추가']}")
        for x in rows:
            nm = f" 이름 {x['got_name']}" + (f" (정답 {x['gold_name']})" if x["gold_name"] and x["got_name"] != x["gold_name"] else "") \
                if x.get("got_name") else ""
            print(f"    [{x['status']}] {x['item']}: 정답 {x['gold']} / 추출 {x['got']}{nm} · {x['basis'] or ''}")
    for f in s["fields"]:
        print(f"  [{f['status']}] {f['item']}: 정답 {f['gold']} / 추출 {f['got']}")
    for p in s["paths"]:
        print(f"  경로 목표 {p['goal']}\n    A [{p['status_A']}] 정답 {p['gold_A']} / 추출 {p['got_A']}"
              f"\n    B [{p['status_B']}] 정답 {p['gold_B']} / 추출 {p['got_B']}")
    for q in s["open_questions"]:
        print(f"  ? {q}")


def datetime_now() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> None:
    ap = argparse.ArgumentParser(prog="tap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="명세 → Tool Registry · API Metadata · API Catalog")
    b.add_argument("--spec", default=str(ROOT / "data/specs/hmall-openapi.json"))
    b.add_argument("--out", default=str(ROOT / "data/out"))
    b.add_argument("--domains", default=str(ROOT / "data/config/domains.yaml"))
    b.add_argument("--services", default=str(ROOT / "data/config/services.yaml"))
    b.add_argument("--overrides", default=str(ROOT / "data/config/overrides.yaml"))
    b.add_argument("--rules", default=str(ROOT / "data/config/rules.ui.yaml"), help="화면에서 넣은 규칙")
    pl = sub.add_parser("plan", help="(예전 방식) 자연어 → 목표 → 경로 → Scenario IR — API 가 적힌 그래프(정답지)에서만")
    pl.add_argument("utterance", nargs="+", help="자연어 요청 (여러 개 가능)")
    pl.add_argument("--graphs", default=str(GOLDEN), help="API 가 적힌 그래프 yaml (기본: 정답지 — data/graphs 는 노드 흐름만이라 안 됨)")
    pl.add_argument("--out", default=str(ROOT / "data/out"))
    pl.add_argument("--goal", default=None, help="LLM 없이 목표 JSON 을 직접 지정")
    pl.add_argument("--model", default=None)
    it = sub.add_parser("intent", help="자연어 → 업무 목록 (도메인 · 신규/기존 · 제약)")
    it.add_argument("utterance", nargs="+", help="자연어 요청 (여러 개 가능)")
    it.add_argument("--model", default=None)
    pa = sub.add_parser("path", help="자연어 → 업무 목록 → 업무마다 그래프 · 출발 · 목표 상태 · 경로")
    pa.add_argument("utterance", nargs="+", help="자연어 요청 (여러 개 가능)")
    pa.add_argument("--tasks", default=None, help="업무 목록 JSON 을 직접 주면 업무 의도 분석(LLM)을 건너뜀")
    pa.add_argument("--model", default=None)
    rn = sub.add_parser("run", help="자연어 → API 선택 → 등록 때 승인 → 실행 때 확인 → 드라이런. 모자라면 실행 거부")
    rn.add_argument("utterance", help="자연어 요청")
    rn.add_argument("--approve", action="store_true", help="등록 때: 시나리오 승인 (쓰기가 있으면)")
    rn.add_argument("--steps", default="", help="등록 때: 직접 확인한 단계 key (예: 1-1,1-2) — 가선택 · LLM 선택")
    rn.add_argument("--confirm", default="", help="실행 때: 이번 실행에서 확인한 R2 단계 key (되돌릴 수 없는 호출)")
    rn.add_argument("--approver", default="권지은")
    rn.add_argument("--model", default=None)
    rn.add_argument("--no-stop-retry", dest="stop_retry", action="store_false", help="중지조건 · 재시도 끄기 (재시도 0회 — 발표 비교용)")
    ev = sub.add_parser("eval", help="태스크셋 채점 — 결과(단계별 정답) · 궤적 · 비용 · 지연")
    ev.add_argument("--tasks", default=str(ROOT / "data/eval/tasks.yaml"))
    ev.add_argument("--ids", default=None, help="일부만 (예: N01,R02)")
    ev.add_argument("--model", default=None)
    ev.add_argument("--no-stop-retry", dest="stop_retry", action="store_false", help="중지조건 · 재시도 끄기 (재시도 0회 — 발표 비교용)")
    ev.add_argument("--out", default=str(ROOT / "data/out/eval"))
    ev.add_argument("--rescore", default=None, help="저장된 채점 결과(json)를 지금 태스크셋 기준으로 다시 채점 (LLM 안 부름)")
    se = sub.add_parser("select", help="자연어 → 업무 목록 → 경로 → 단계마다 API (+ 구분값)")
    se.add_argument("utterance", nargs="+", help="자연어 요청 (여러 개 가능)")
    se.add_argument("--tasks", default=None, help="업무 목록 JSON 을 직접 주면 업무 의도 분석(LLM)을 건너뜀")
    se.add_argument("--model", default=None)
    se.add_argument("--no-stop-retry", dest="stop_retry", action="store_false", help="중지조건 · 재시도 끄기 (재시도 0회 — 발표 비교용)")
    ex = sub.add_parser("extract-graph", help="(실험) 공통코드 + 명세만으로 그래프 재료 추출 → 정답지와 채점")
    ex.add_argument("--codes", default=str(ROOT / "data/codes/common_codes.csv"))
    ex.add_argument("--group", default="ORD_STAT_GBCD")
    ex.add_argument("--domain", default="od", help="그래프 담당 도메인 = 상태 코드 그룹의 주인")
    ex.add_argument("--golden", default=str(GOLDEN))
    ex.add_argument("--out", default=str(ROOT / "data/out"))
    ex.add_argument("--model", default=None)
    ex.add_argument("--runs", type=int, default=1, help="같은 입력으로 몇 번 돌릴지 (흔들림 확인)")
    ex.add_argument("--rescore", nargs="+", default=None, help="LLM 없이 이미 추출한 yaml 을 다시 채점")
    mg = sub.add_parser("match-graph", help="화살표 이름 · 상태만으로 API 후보 찾기 → 정답지와 채점")
    mg.add_argument("--golden", default=str(GOLDEN))
    mg.add_argument("--out", default=str(ROOT / "data/out"))
    mg.add_argument("--domains", default="pd,od,ds")
    sub.add_parser("ui-data", help="실제 산출물 → prototype/tap-data.js (오프라인 UI 가 읽는다)")
    sv = sub.add_parser("serve", help="오프라인 UI 로컬 서버 — 시나리오 생성 · 그래프 저장을 실제로 실행")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--host", default="127.0.0.1", help="WSL 밖 브라우저에서 안 열리면 0.0.0.0")
    a = ap.parse_args()
    if a.cmd == "ui-data":
        from tap.ui.export import write_ui_data
        print(write_ui_data(ROOT, ROOT / "prototype/tap-data.js"))
        return
    if a.cmd == "serve":
        from tap.ui.export import write_ui_data
        from tap.ui.serve import serve
        write_ui_data(ROOT, ROOT / "prototype/tap-data.js")
        serve(ROOT, a.port, a.host)
        return
    if a.cmd == "match-graph":
        r = match_graph(Path(a.golden), Path(a.out), a.domains.split(","))
        for k, v in r["summary"].items():
            print(f"■ {k}: {v}")
        for x in r["rows"]:
            print(f"  [{x['result']} · {x['status']}] {x['kind']} {x['item']}  정답 {x['want']}  후보 {x['top'][:2]}")
        return
    if a.cmd == "extract-graph" and a.rescore:
        for r in rescore([Path(f) for f in a.rescore], a.group, Path(a.golden)):
            _print_score(r)
        return
    if a.cmd == "extract-graph":
        for i in range(1, a.runs + 1):
            r = extract_graph(Path(a.codes), a.group, Path(a.golden) if a.golden else None, Path(a.out),
                              a.model, str(i), a.domain)
            if "score" in r:
                _print_score(r)
        return
    if a.cmd == "intent":
        for u in a.utterance:
            r = analyze_intent(u, model=a.model)
            print(r["plan"].model_dump_json(indent=2))
            for n in r["notes"]:
                print(f"  (검사) {n}")
        return
    if a.cmd == "run":
        from tap.apis.gate import GateError, approve, dry_run
        r = analyze_select(a.utterance, rules_cfg=ROOT / "data/config/rules.ui.yaml", model=a.model, stop_retry=a.stop_retry)
        g, sel = r["gate"], r["apis"]
        print(f"■ {a.utterance}\n  선택 결과 {sel.status} · 승인 게이트 {g.status}")
        for st in g.steps:
            api = f"{st.api_id.rsplit('/', 1)[-1]} {st.selector}" if st.api_id else "-"
            print(f"  [{st.key}] {st.kind} '{st.edge}' → {api} | {st.tier or '-'} · 등록 때 {st.requirement}"
                  + (" · 실행 때 확인" if st.confirm_on_run else "") + f" | {'; '.join(st.reasons)}")
        for b_ in g.blocked:
            print(f"  차단: {b_}")
        try:                                    # 등록 때 승인 — 승인본 고정
            ap = approve(g, a.approver, a.approve, [k for k in a.steps.split(",") if k]) if g.status != "자동" else None
        except GateError as e:
            print(f"  ✗ 실행 거부 (등록 때 승인) — {e}")
            print(r["trace"].summary())
            return
        if ap:
            d = ROOT / "data/approved"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{ap.selection_hash.split(':')[1][:12]}.json"
            f.write_text(json.dumps({"request": a.utterance, "approval": ap.model_dump(), "gate": g.model_dump(),
                                     "selection": sel.dump()}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✓ 등록 때 승인 {ap.approver} · {ap.at} → {f.relative_to(ROOT)}")
        try:                                    # 실행 때 확인 — R2 는 실행할 때마다
            calls = dry_run(sel, g, ap, [k for k in a.confirm.split(",") if k])
        except GateError as e:
            print(f"  ✗ 실행 거부 — {e}")
            print(r["trace"].summary())
            return
        print("  드라이런 (실제 호출 안 함):")
        for c in calls:
            print(f"    {c['key']} {c['kind']} {c['api_id'].rsplit('/', 1)[-1]} {c['selector']} ({c['tier']})")
        print(r["trace"].summary())
        return
    if a.cmd == "eval":
        import os
        from tap import evaluate as E
        cases = E.load_tasks(a.tasks)
        if a.ids:
            cases = [c for c in cases if c["id"] in a.ids.split(",")]
        results = []
        if a.rescore:
            saved = json.loads(Path(a.rescore).read_text(encoding="utf-8"))
            results = E.rescore(saved, cases)
            cases = []
        for c in cases:
            r = E.run_case(c, lambda u: analyze_select(u, rules_cfg=ROOT / "data/config/rules.ui.yaml", model=a.model, stop_retry=a.stop_retry,
                                                       trace_dir=Path(a.out) / "traces"))
            t = r["trajectory"]
            print(f"  {c['id']} {'O' if r['passed'] else 'X'} {r['final_status']} · LLM {t['llm_calls']} · {t['ms']}ms"
                  + (f" · 처음 틀린 단계 {r['first_fail']}" if r["first_fail"] else "") + (f" · 뚫림 {r['violations']}" if r.get("violations") else ""), flush=True)
            results.append(r)
        summary = E.summarize(results)
        meta = {"at": datetime_now(), "model": a.model or os.environ.get("OPENAI_DEFAULT_MODEL") or (saved["meta"].get("model") if a.rescore else None),
                "tasks_file": a.tasks, "stop_retry": a.stop_retry, **({"rescored_from": a.rescore} if a.rescore else {})}
        j, m = E.save(results, summary, meta, a.out)
        print(m.read_text(encoding="utf-8").split("\n\n| id |")[0])
        print(f"→ {m}\n→ {j}")
        return
    if a.cmd == "select":
        for u in a.utterance:
            from tap.trace import Stopped
            try:
                r = analyze_select(u, rules_cfg=ROOT / "data/config/rules.ui.yaml", model=a.model, tasks_json=a.tasks, stop_retry=a.stop_retry)
            except Stopped as e:
                print(f"■ {u}\n  {e}")
                continue
            print(json.dumps({"tasks": r["tasks"].model_dump(), "paths": r["paths"].dump(), "apis": r["apis"].dump()},
                             ensure_ascii=False, indent=2))
            for n in r["notes"]:
                print(f"  (검사) {n}")
            print(r["trace"].summary() + f"\n  → {r['trace_file']}")
        return
    if a.cmd == "path":
        for u in a.utterance:
            r = analyze_paths(u, rules_cfg=ROOT / "data/config/rules.ui.yaml", model=a.model, tasks_json=a.tasks)
            print(json.dumps({"tasks": r["tasks"].model_dump(), "paths": r["paths"].dump()}, ensure_ascii=False, indent=2))
            for n in r["notes"]:
                print(f"  (검사) {n}")
        return
    if a.cmd == "plan":
        for u in a.utterance:
            r = plan_request(u, Path(a.graphs) if a.graphs else [GRAPH_DIR], Path(a.out), a.goal, a.model, ROOT / "data/config/rules.ui.yaml")
            _print_ir(r["ir"])
            print(f"  → {r['file']}")
        return
    if a.cmd == "build":
        r = build(Path(a.spec), Path(a.out), Path(a.domains), Path(a.services), Path(a.overrides), rules_cfg=Path(a.rules))
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
