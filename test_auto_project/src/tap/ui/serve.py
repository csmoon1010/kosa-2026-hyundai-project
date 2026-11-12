"""로컬 서버 — 오프라인 UI 를 띄우고, 구현된 기능은 실제로 실행한다.

    PYTHONPATH=src python -m tap.cli serve        → http://127.0.0.1:8765/offline-ui.html

  GET  /tap-data.js          산출물을 매번 새로 읽어 내려준다
  GET  /api/health           화면이 서버 모드인지 확인
  POST /api/select           {utterance} → ① 의도 분석 → ② 경로 탐색 → ③ API 선택 → 권한 등급 · 승인 게이트 (+ 트레이스)
                             Accept: application/x-ndjson 이면 단계 시작마다 {"event":"stage","stage":…} 후 {"event":"done"|"error",…}
  POST /api/approve          {selection_hash, scenario, steps, approver} → 등록 때 승인 (서버가 계산한 게이트로 확인) → 승인본 data/approved/
  POST /api/run              {selection_hash, confirm} → 실행 때 확인 (승인본 · 해시 · R2 단계 확인) → 드라이런
  POST /api/graph/save       {graph_id, yaml} → data/graphs/<id>.yaml (노드 흐름만, 기존 파일 위에 합침 — 진입 상태 · 상태 필드 · 확인 키 유지, 이전 파일은 data/out/graph_history/)
  POST /api/rules            {place, doc, item, dom, target, body} → data/config/rules.ui.yaml + 다시 빌드 → 새 TAP_DATA
  POST /api/rules/delete     {id} → 화면 규칙 삭제 + 다시 빌드
  POST /api/baseline         {api_id, body} → data/baselines/<api>.json
  ── 혜정: Baseline · Parameter KB 참조 → 입력값 매핑 → Output Binding → Scenario IR 초안 (승인 뒤에만) ──
  POST /api/preprocessing/refresh   생성된 전처리 JSON 재조회 + tap-data.js 갱신 (노트북 실행 없음)
  POST /api/preprocessing/baseline  {selected_api_id, values} → data/baselines/preprocessing/*.json
  POST /api/approved-selections     {filename, approved_json} → prototype/approved/<filename>.json
  POST /api/scenario-ir-drafts      {approved_filename, …} → IR 초안 (Accept: application/x-ndjson 이면 실시간 진행)
  GET  /api/approved-selections · /api/scenario-ir-budget · /api/scenario-ir-log-summaries · /api/scenario-ir-logs/<파일>
  GET/POST /api/scenario-ir-reviews/…   IR 입력 검토
  /api/approve 가 승인에 성공하면 혜정 형식 승인본(prototype/approved/tdg-*.json)도 만들어 준다 (tap.ir.handoff)
  POST /api/review-draft     {selection_hash} → 승인 전 검토용 초안 prototype/approved/review-*.json (최종 등록 화면 — 분석 → IR → 승인)
  POST /api/register         {selection_hash, name, approver, steps, review_file, ir_file} → 승인 + 등록 data/registered/<id>.json
  GET  /api/registered/<id>  등록 시나리오 전체 · POST /api/registered/delete {id}
  POST /api/registered/run   {items: [{id, n, confirm}]} → 실행 확인(승인 · 해시 · R2 단계) → IR 로 드라이런 → data/runs/
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

from tap.ui.export import ui_data, write_ui_data
from tap.ui.preprocessing import save_preprocessing_baseline


def scenario_ir_log_summaries(root: Path) -> list[dict]:
    """Summarize every persisted scenario-IR JSONL run without exposing prompts."""
    folder = root / 'data/out/scenario_ir_logs'
    summaries = []
    if not folder.is_dir():
        return summaries
    for file in folder.glob('IRRUN-*.jsonl'):
        start = None
        latest_usage = {}
        budget = None
        budget_usage = {}
        budget_reason = None
        request_turns = set()
        request_count = attempt_count = 0
        status = '미완료'
        last_recorded_at = None
        duration = 0.0
        try:
            with file.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    kind = event.get('event')
                    budget = event.get('budget') or budget
                    budget_usage = event.get('budget_usage') or budget_usage
                    budget_reason = event.get('budget_reason') or event.get('reason_code') or budget_reason
                    if kind == 'generation_start':
                        start = event
                    if kind == 'llm_request':
                        request_count += 1
                        if event.get('turn') is not None:
                            request_turns.add(event['turn'])
                    if kind == 'llm_attempt_start':
                        attempt_count += 1
                    usage = event.get('usage')
                    if isinstance(usage, dict):
                        for key, value in usage.items():
                            if isinstance(value, (int, float)):
                                latest_usage[key] = max(latest_usage.get(key, value), value)
                    recorded = event.get('recorded_at')
                    if recorded:
                        last_recorded_at = recorded
                    if isinstance(event.get('run_elapsed_seconds'), (int, float)):
                        duration = max(duration, event['run_elapsed_seconds'])
                    if kind == 'generation_complete':
                        status = '완료'
                        result_usage = (event.get('result') or {}).get('usage')
                        if isinstance(result_usage, dict):
                            latest_usage.update({k:v for k,v in result_usage.items()
                                                 if isinstance(v, (int,float))})
                        result_duration = (event.get('result') or {}).get('usage', {}).get('elapsed_seconds')
                        if isinstance(result_duration, (int,float)):
                            duration = max(duration, result_duration)
                    elif kind == 'generation_error':
                        status = '실패'
                    elif kind == 'recovery_stopped':
                        status = '중단'
            if start is None:
                continue
            if not duration and last_recorded_at and start.get('recorded_at'):
                try:
                    duration = max(0.0, (datetime.fromisoformat(last_recorded_at) -
                                          datetime.fromisoformat(start['recorded_at'])).total_seconds())
                except (TypeError, ValueError):
                    pass
            if budget is None and isinstance(start.get('config'),dict):
                c=start['config']
                budget=dict(version='legacy_fixed_v1', limits=dict(llm_calls=c.get('max_turns'),tokens=c.get('max_tokens'),seconds=c.get('max_seconds')))
            attempts = max(attempt_count, request_count)
            calls = max(int(latest_usage.get('llm_calls', 0)), attempts)
            options = start.get('options')
            if options is None and start.get('execution_mode') in ('basic', 'validated'):
                options = {'stop_retry': start['execution_mode'] == 'validated',
                           'kb_rag': False, 'dependency_projection': False}
            summaries.append({
                'run_id': start.get('run_id', file.stem), 'filename': file.name,
                'started_at': start.get('recorded_at'), 'options': options,
                'status': status, 'duration_seconds': round(duration, 3),
                'budget': budget, 'budget_usage': budget_usage, 'budget_reason':budget_reason,
                'step_count': (budget or {}).get('step_count'),
                'embedding_calls': latest_usage.get('embedding_calls'),
                'model_calls': budget_usage.get('llm_calls',calls), 'turns': len(request_turns),
                'input_tokens': int(latest_usage.get('input_tokens', 0)),
                'output_tokens': int(latest_usage.get('output_tokens', 0)),
                'embedding_tokens': int(latest_usage.get('embedding_tokens', 0)),
                'total_tokens': int(latest_usage.get('total_tokens', 0)),
            })
        except OSError:
            continue
    summaries.sort(key=lambda row: row.get('started_at') or '', reverse=True)
    return summaries


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


def _registered_path(root: Path, sid: str) -> Path:
    p = root / "data/registered" / (re.sub(r"[^A-Za-z0-9\-]", "", str(sid)) + ".json")
    if not p.exists():
        raise ValueError(f"없는 시나리오: {sid}")
    return p


def register_scenario(root: Path, body: dict, pending: dict) -> dict:
    """최종 등록 화면 — 승인하고 등록한다 (2026-11-12). 승인 판단은 서버가 계산한 게이트로 (화면 값은 믿지 않는다).

    IR 은 승인 전에 검토 전 초안(review-*.json)으로 만들었다 → 그 초안과 IR 이 이 분석 결과(선택 해시)로 만든 것인지 확인하고,
    분석 결과 · 게이트 · 승인 · IR 을 한 파일로 고정한다. 단계 대응(step_map): IR 단계 번호 ↔ ③ 단계 key.
    """
    from tap.apis.gate import approve
    from tap.ir.draft_build import approved_path
    name = str(body.get("name") or "").strip()
    approver = str(body.get("approver") or "").strip()
    if not name:
        raise ValueError("시나리오 이름을 적으세요")
    if not approver:
        raise ValueError("승인자를 적으세요")
    g = pending["gate"]
    if g.status in ("차단", "실행할 것 없음"):
        raise ValueError(f"게이트 {g.status} — 등록할 수 없습니다")
    review_file = str(body.get("review_file") or "")
    review = json.loads(approved_path(root, review_file).read_text(encoding="utf-8-sig"))
    if review.get("approval_status") != "review" or (review.get("tdg_review") or {}).get("selection_hash") != g.selection_hash:
        raise ValueError("검토 전 초안이 이 분석 결과로 만든 것이 아닙니다 — 다시 분석하세요")
    ir_name = Path(str(body.get("ir_file") or "")).name
    ir_path = root / "data/out/scenario_ir_drafts" / ir_name
    if not re.fullmatch(r"SCN-[A-Za-z0-9\-]+\.json", ir_name) or not ir_path.is_file():
        raise ValueError("시나리오(IR) 파일이 없습니다 — 시나리오 생성이 끝난 뒤 등록하세요")
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    if ((ir.get("sources") or {}).get("approved") or {}).get("file") != f"prototype/approved/{review_file}":
        raise ValueError("시나리오(IR)가 이 분석 결과로 만든 것이 아닙니다 — 다시 만드세요")
    ap = approve(g, approver, bool(g.need_scenario), list(body.get("steps") or []))      # 모자라면 GateError
    pending["approval"] = ap
    cat = json.loads((root / "data/out/api_catalog.json").read_text(encoding="utf-8")) if (root / "data/out/api_catalog.json").exists() else {}
    sid, at = _stamp()
    tasks = pending["tasks"].model_dump()
    rec = {"id": "rs-" + sid, "format": "registered-v1", "name": name, "utterance": pending["request"],
           "domains": sorted({str(t["domain"]).lower() for t in tasks["tasks"]}), "registered_at": at,
           "catalog_version": cat.get("catalog_version"), "approval": ap.model_dump(), "gate": g.model_dump(),
           "tasks": tasks, "paths": pending["paths"].dump(), "selection": pending["apis"].dump(),
           "step_map": [{"step_id": f"{r['path_sequence']}-{r['step']}", "source_step": r["source_step"]} for r in review["api_selection_results"]],
           "review_file": review_file, "ir_file": str(ir_path.relative_to(root)), "ir": ir, "trace_file": pending.get("trace_file")}
    dest = root / "data/registered" / f"{rec['id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rec


def run_registered(root: Path, body: dict) -> dict:
    """실행 메뉴 — 등록 시나리오 드라이런 (2026-11-12, P4). API 를 부르지 않고 IR 로 요청을 만들어 이력에 남긴다.

    시나리오마다 실행 확인(assert_executable): 승인본 · 선택 해시 · 이번 실행에서 확인한 R2 단계. 하나라도 안 되면 아무것도 남기지 않는다.
    API 명세(카탈로그)가 등록 뒤 바뀌었으면 재승인 필요로 거부. 요청 XML = Baseline 에 IR 입력값을 덮은 것 (앞 단계 값은 {{…}}).
    """
    from tap.apis.gate import Approval, Gate, GateError, dry_run
    from tap.apis.select import ApiSelection
    from tap.ir.xml_preview import build_xml_preview
    items = body.get("items") or []
    if not items:
        raise ValueError("실행할 시나리오를 고르세요")
    cat_path = root / "data/out/api_catalog.json"
    cat_ver = json.loads(cat_path.read_text(encoding="utf-8")).get("catalog_version") if cat_path.exists() else None
    base_dir = (root / "data/out/parameters").resolve()
    rows, calls, unresolved, rollback = [], [], [], []
    for it in items:
        rec = json.loads(_registered_path(root, it.get("id")).read_text(encoding="utf-8"))
        n = int(it.get("n") or 1)
        if not 1 <= n <= 20:
            raise ValueError(f"'{rec['name']}': 반복 횟수는 1~20")
        if rec.get("catalog_version") and cat_ver and rec["catalog_version"] != cat_ver:
            raise ValueError(f"'{rec['name']}': 등록 뒤 API 명세가 바뀌었습니다 — 다시 등록(재승인)하세요")
        confirm = [str(k) for k in it.get("confirm") or []]
        try:
            dry_run(ApiSelection.model_validate(rec["selection"]), Gate.model_validate(rec["gate"]),
                    Approval.model_validate(rec["approval"]), confirm)
        except GateError as e:
            raise ValueError(f"'{rec['name']}': {e}") from e
        tier = {s["key"]: s["tier"] for s in rec["gate"]["steps"]}
        src = {m["step_id"]: m["source_step"] for m in rec.get("step_map") or []}
        rows.append({"scenario_id": rec["id"], "name": rec["name"], "count": n, "confirmed": confirm})
        steps = [s for t in (rec.get("ir") or {}).get("tasks") or [] for s in t.get("steps") or []]
        for k in range(1, n + 1):
            for s in steps:
                xml = None
                if k == 1:                              # 반복해도 요청 모양은 같다 — 첫 번만 만든다
                    f = (root / str((s.get("baseline") or {}).get("file") or "")).resolve()
                    if f.is_file() and base_dir in f.parents:
                        pv = build_xml_preview(json.loads(f.read_text(encoding="utf-8")).get("baseline_xml"), s.get("inputs") or [], s.get("bindings") or [])
                        xml = pv["applied_xml"] if pv["available"] else None
                t = tier.get(src.get(s["step_id"]))
                calls.append({"scenario": rec["name"], "scenario_id": rec["id"], "k": k, "step_id": s["step_id"], "name": s.get("edge"),
                              "api_id": (s.get("api") or {}).get("api_id"), "tier": t, "xml": xml,
                              "inputs": [{kk: x.get(kk) for kk in ("field", "source", "value", "ref")} for x in s.get("inputs") or []],
                              "bindings": [{"binding_id": b.get("binding_id"), "from_step_id": (b.get("from") or {}).get("from_step_id"),
                                            "output_name": (b.get("from") or {}).get("output_name")} for b in s.get("bindings") or []]})
                if t in ("R1", "R2"):
                    rollback.insert(0, {"name": f"{rec['name']} #{k} {s.get('edge')}", "with": "되돌리는 화살표 있음" if t == "R1" else None})
        unresolved += [f"{rec['name']} · {u.get('reason')}" for u in (rec.get("ir") or {}).get("unresolved") or [] if u.get("status") == "open"]
    return save_run(root, {"rows": rows, "calls": calls, "unresolved": unresolved, "rollback": rollback})


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


def save_approved_selection(root: Path, body: dict) -> dict:
    """의도와 API 선택 승인을 prototype/approved 에 통합 JSON 으로 저장한다."""
    data = body.get("approved_json")
    if not isinstance(data, dict):
        raise ValueError("approved_json은 JSON 객체여야 합니다")
    if not str(data.get("original_question") or "").strip():
        raise ValueError("original_question이 필요합니다")
    if data.get("approval_status") not in {"approved", "unapproved"}:
        raise ValueError("approval_status는 approved 또는 unapproved여야 합니다")
    if not isinstance(data.get("intent_tasks"), list) or not data["intent_tasks"]:
        raise ValueError("intent_tasks가 필요합니다")
    rows = data.get("api_selection_results")
    if not isinstance(rows, list) or not rows:
        raise ValueError("api_selection_results가 필요합니다")
    statuses = [row.get("approval_status") if isinstance(row, dict) else None for row in rows]
    if any(status not in {"approved", "unapproved"} for status in statuses):
        raise ValueError("각 API 선택 결과의 approval_status는 approved 또는 unapproved여야 합니다")
    if data["approval_status"] == "approved" and any(status != "approved" for status in statuses):
        raise ValueError("미승인 API가 있어 전체 승인 상태를 approved로 저장할 수 없습니다")

    requested = Path(str(body.get("filename") or "api-selection-approved.json")).name
    filename = re.sub(r"[^A-Za-z0-9._-]", "-", requested).strip(".-") or "api-selection-approved.json"
    if not filename.lower().endswith(".json"):
        filename += ".json"
    dest_dir = root / "prototype/approved"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if dest.exists():
        stamp, _ = _stamp()
        dest = dest_dir / f"{dest.stem}-{stamp}{dest.suffix}"
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"file": str(dest.relative_to(root)), "filename": dest.name}


def make_handler(root: Path, llm=None):
    """llm: 테스트에서 가짜 LLM 을 끼울 때. 없으면 .env 의 OpenAI."""
    proto = root / "prototype"
    pending: dict[str, dict[str, Any]] = {}    # selection_hash → 서버가 계산한 선택 결과 · 게이트 (승인은 이것으로만 확인한다)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(proto), **kw)

        def end_headers(self):
            # 화면 파일(html · js · css)을 브라우저가 옛것으로 쓰지 않게 — 매번 서버에 바뀌었는지 묻는다 (2026-11-05)
            if not any(h.lower().startswith(b"cache-control") for h in getattr(self, "_headers_buffer", [])):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def _json(self, code: int, body) -> None:
            raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == '/api/scenario-ir-reviews' or path.startswith('/api/scenario-ir-reviews/'):
                from tap.ir.input_review import list_reviews, load
                try:
                    if path == '/api/scenario-ir-reviews':
                        return self._json(200, {'reviews':list_reviews(root)})
                    return self._json(200, load(root, path.removeprefix('/api/scenario-ir-reviews/')))
                except ValueError as error:
                    return self._json(400, {'error':str(error)})
            if path == "/tap-data.js":
                raw = ("window.TAP_DATA = " + json.dumps(ui_data(root), ensure_ascii=False) + ";\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if path == '/api/scenario-ir-log-summaries':
                return self._json(200, {'runs': scenario_ir_log_summaries(root)})
            if path.startswith('/api/scenario-ir-logs/'):
                name = path.rsplit('/', 1)[-1]
                folder = (root / 'data/out/scenario_ir_logs').resolve()
                file = (folder / name).resolve()
                if not re.fullmatch(r'IRRUN-[A-Za-z0-9-]+\.jsonl', name) or file.parent != folder or not file.is_file():
                    return self._json(404, {'error': '로그 파일이 없습니다'})
                raw = file.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="' + name + '"')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if path == "/api/approved-selections":
                from tap.agent.config import DEFAULTS, DEFAULT_OPTIONS, DEFAULT_GENERATION_MODE, GENERATION_MODES
                rows = []
                for file in sorted((root / "prototype/approved").glob("*.json")):
                    try:
                        data = json.loads(file.read_text(encoding="utf-8-sig"))
                        if data.get("approval_status") == "review":      # 최종 등록 화면의 검토 전 초안 — 확인용 목록엔 승인본만
                            continue
                        rows.append({"filename": file.name, "original_question": data.get("original_question"), "approval_status": data.get("approval_status")})
                    except (ValueError, OSError):
                        continue
                return self._json(200, {"files": rows, "defaults": DEFAULTS,
                                        "default_generation_options": dict(DEFAULT_OPTIONS),
                                        "default_generation_mode": DEFAULT_GENERATION_MODE, "generation_modes": GENERATION_MODES})
            if path == '/api/scenario-ir-budget':
                from urllib.parse import parse_qs, urlsplit
                from tap.ir.draft_build import approved_path, fixed_plan
                from tap.agent.budget import calculate
                try:
                    filename = parse_qs(urlsplit(self.path).query).get('filename',[''])[0]
                    approved = json.loads(approved_path(root,filename).read_text(encoding='utf-8-sig'))
                    return self._json(200, {'budget':calculate(len(fixed_plan(approved)))})
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {'error':str(error)})
            if path.startswith("/api/registered/"):
                try:
                    return self._json(200, json.loads(_registered_path(root, path.rsplit("/", 1)[1]).read_text(encoding="utf-8")))
                except ValueError as e:
                    return self._json(404, {"error": str(e)})
            if path == "/api/health":
                return self._json(200, {"ok": True})
            if path == "/":
                self.path = "/offline-ui.html"
            return super().do_GET()

        def _select_result(self, body: dict[str, Any], on_stage=None) -> tuple[int, dict[str, Any]]:
            from tap.cli import analyze_select
            utt = str(body.get("utterance") or "").strip()
            if not utt:
                raise ValueError("자연어 요청이 비어 있습니다")
            try:
                r = analyze_select(utt, [root / "data/graphs"], root / "data/out", root / "data/config/rules.ui.yaml",
                                   llm=llm, trace_dir=root / "data/out/traces", stop_retry=body.get("stop_retry", True) is not False,
                                   on_stage=on_stage)
            except Exception as e:                  # 검사 거절 · 예산 초과도 트레이스와 함께 화면에 보여 준다
                tr = getattr(e, "trace", None)
                return 400, {"error": f"{type(e).__name__}: {e}", "trace": tr.to_dict() if tr else None}
            g = r["gate"]
            pending[g.selection_hash] = {"request": utt, "apis": r["apis"], "gate": g, "tasks": r["tasks"], "paths": r["paths"],
                                         "trace_file": str(Path(r["trace_file"]).relative_to(root))}
            return 200, {"request": utt, "tasks": r["tasks"].model_dump(), "paths": r["paths"].dump(),
                         "apis": r["apis"].dump(), "gate": g.model_dump(), "trace": r["trace"].to_dict(),
                         "notes": r["notes"], "trace_file": str(Path(r["trace_file"]).relative_to(root))}

        def _select(self, body: dict[str, Any]) -> None:
            return self._json(*self._select_result(body))

        def _select_stream(self, body: dict[str, Any]) -> None:
            """최종 등록 화면 — 단계를 시작할 때마다 한 줄씩 보낸다 (진행 표시). 마지막 줄이 결과 (2026-11-12)."""
            if not str(body.get("utterance") or "").strip():
                raise ValueError("자연어 요청이 비어 있습니다")
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()

            def emit(event: dict[str, Any]) -> None:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8'))
                self.wfile.flush()
            try:
                code, result = self._select_result(body, on_stage=lambda s: emit({"event": "stage", "stage": s}))
                emit({"event": "done" if code == 200 else "error", "result": result})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                try:
                    emit({"event": "error", "result": {"error": f"{type(error).__name__}: {error}"}})
                except (BrokenPipeError, ConnectionResetError):
                    pass
            self.close_connection = True

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
            return self._json(200, {"approval": ap.model_dump(), "file": str(f.relative_to(root)), "confirm_steps": g.confirm_steps,
                                    "ir_handoff": self._handoff(p, ap, f)})

        def _review_draft(self, body: dict[str, Any]) -> None:
            """최종 등록 화면 — 승인 전에 IR 을 만들어 보기 위한 검토 전 초안 (2026-11-12). 차단이면 만들지 않는다."""
            p = self._pending(body)
            if p["gate"].status in ("차단", "실행할 것 없음"):
                return self._json(400, {"error": f"게이트 {p['gate'].status} — 시나리오를 만들 수 없습니다"})
            h = self._handoff(p, None, None)
            return self._json(200 if h.get("filename") else 400, h)

        def _handoff(self, p: dict[str, Any], ap, f: Path | None) -> dict[str, Any]:
            """혜정 IR 초안 생성으로 — 혜정 형식 승인본을 만들고, 혜정의 fixed_plan 으로 미리 확인한다.
            ap 가 없으면 검토 전 초안(review) — 최종 등록 화면이 승인 전에 IR 을 만든다."""
            from tap.ir.draft_build import fixed_plan
            from tap.ir.handoff import hyejung_approved, missing_materials, save_hyejung_approved
            try:
                data = hyejung_approved(p["tasks"], p["paths"], p["apis"], p["gate"], ap,
                                        {**({"tdg_approval": str(f.relative_to(root))} if f else {}), "trace": p.get("trace_file")})
                plan = fixed_plan(json.loads(json.dumps(data)))
                missing = missing_materials(root, data, plan)
                if missing:                     # IR 생성 도중 자료 없음(fatal)으로 멈추기 전에 승인 때 알린다
                    return {"filename": None, "error": "IR 생성에 필요한 자료가 없어 넘기지 않음: " + "; ".join(missing), "missing": missing}
                name = save_hyejung_approved(root, data)
            except (ValueError, KeyError) as e:
                return {"filename": None, "error": f"IR 초안 생성으로 넘기지 못함: {e}"}
            return {"filename": name, "file": f"prototype/approved/{name}", "steps": [
                {"step_id": f"{r['path_sequence']}-{r['step']}", "source_step": r["source_step"]} for r in data["api_selection_results"]]}

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

        def _guard_human_values(self, values) -> None:
            """사람이 넣는 값에 지시문이 있으면 저장하지 않는다 (요청 원문과 같은 지시문 낱말 · 2026-11-05 병합)."""
            from tap.apis.gate import detect_in_values, load_permissions
            hits = detect_in_values(values, load_permissions(root / "data/config/permissions.yaml"))
            if hits:
                raise ValueError("입력값 속 지시문 감지 — 저장하지 않음 [INJECTION_BLOCKED]: " + "; ".join(hits))

        def _stream_draft(self, root, body):
            from tap.ir.draft_build import generate
            from tap.agent.progress import snapshot
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            def emit(event):
                self.wfile.write((json.dumps(snapshot(event), ensure_ascii=False) + '\n').encode('utf-8'))
                self.wfile.flush()
            try:
                mode = {key: body[key] for key in ('generation_mode', 'generation_options') if key in body}
                result = generate(root, body.get('approved_filename'), body.get('generation_config'), on_event=emit, **mode)
                # Successful IR retains the original values; only log snapshots are redacted.
                self.wfile.write((json.dumps({'event': 'generation_complete', 'result': result}, ensure_ascii=False) + '\n').encode('utf-8'))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                try: emit({'event': 'generation_error', 'error': str(error), 'log_file': getattr(error, 'log_file', None), 'log_url': getattr(error, 'log_url', None)})
                except (BrokenPipeError, ConnectionResetError): pass
            self.close_connection = True

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError('요청은 JSON 객체여야 합니다')
                if self.path.startswith('/api/scenario-ir-reviews/') or self.path == "/api/preprocessing/baseline":
                    self._guard_human_values(body.get("decisions") if self.path.startswith('/api/scenario-ir-reviews/') else body.get("values"))
                if self.path.startswith('/api/scenario-ir-reviews/'):
                    from tap.ir.input_review import submit
                    match = re.fullmatch(r'/api/scenario-ir-reviews/([^/]+)/(decisions|confirm)', self.path)
                    if not match:
                        raise ValueError('올바른 검토 경로가 필요합니다')
                    return self._json(200, submit(root, match[1], body, confirm=match[2]=='confirm'))
                if self.path == "/api/scenario-ir-drafts":
                    from tap.ir.draft_build import generate
                    from tap.agent.config import generation_options
                    generation_options(body.get('generation_options'), body.get('generation_mode'))
                    if "budget_policy" in body or "budget" in body:
                        raise ValueError("예산은 서버에서 자동 산정합니다")
                    if 'application/x-ndjson' in self.headers.get('Accept', ''):
                        return self._stream_draft(root, body)
                    mode = {key: body[key] for key in ('generation_mode', 'generation_options') if key in body}
                    return self._json(200, generate(root, body.get("approved_filename"), body.get("generation_config"), **mode))
                if self.path == "/api/select":
                    if 'application/x-ndjson' in self.headers.get('Accept', ''):
                        return self._select_stream(body)
                    return self._select(body)
                if self.path == "/api/approve":
                    return self._approve(body)
                if self.path == "/api/review-draft":
                    return self._review_draft(body)
                if self.path == "/api/register":
                    from tap.apis.gate import GateError
                    try:
                        rec = register_scenario(root, body, self._pending(body))
                    except GateError as e:
                        return self._json(400, {"error": str(e), "refused": True})
                    from tap.ui.export import registered_summary
                    return self._json(200, {"scenario": registered_summary(rec), "id": rec["id"]})
                if self.path == "/api/registered/run":
                    return self._json(200, {"run": run_registered(root, body)})
                if self.path == "/api/registered/delete":
                    _registered_path(root, body.get("id")).unlink()
                    return self._json(200, {"ok": True})
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
                if self.path == "/api/preprocessing/refresh":
                    # 노트북은 실행하지 않고 이미 생성된 JSON을 다시 읽어 정적 화면에도 반영한다.
                    write_ui_data(root, root / "prototype/tap-data.js")
                    return self._json(200, {"data": ui_data(root)})
                if self.path == "/api/preprocessing/baseline":
                    dest = save_preprocessing_baseline(root, body["selected_api_id"], body["values"])
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
                if self.path == "/api/approved-selections":
                    return self._json(200, save_approved_selection(root, body))
                return self._json(404, {"error": "없는 경로"})
            except Exception as e:                              # 화면에 그대로 보여 준다
                from tap.ir.input_review import ReviewConflict
                code = 409 if isinstance(e, ReviewConflict) else 400 if isinstance(e, ValueError) else 500
                return self._json(code, {"error": str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}", "log_file": getattr(e, "log_file", None), "log_url": getattr(e, "log_url", None)})

    return Handler


def serve(root: Path, port: int = 8765, host: str = "127.0.0.1") -> None:
    """host 기본은 이 컴퓨터에서만. WSL 밖(Windows 브라우저)에서 localhost 로 안 열리면 --host 0.0.0.0 으로 띄우고 WSL IP 로 연다."""
    httpd = ThreadingHTTPServer((host, port), make_handler(root))
    print(f"오프라인 UI → http://127.0.0.1:{port}/  (상태 그래프만: /graph-editor.html, 끝내려면 Ctrl+C)", flush=True)
    httpd.serve_forever()
