"""①②③ + 승인 → 혜정 IR 초안 생성의 입력(승인본 JSON). 혜정 코드는 고치지 않고 형식만 맞춘다.

혜정 쪽(tap.ir.draft_build)은 prototype/approved/<파일>.json 을 읽어 Baseline · Parameter KB 참조 → 입력값 매핑 →
Output Binding → Scenario IR 초안을 만든다. 우리 승인(/api/approve)이 성공했을 때만 이 파일을 만든다.

형식을 맞추는 곳 (2026-11-03 지은 결정)
  단계 번호   혜정은 1 이상만 받는다 → 업무마다 1부터 다시 매기고, 우리 단계 key(1-0 …)는 source_step 에 남긴다
  구분값      혜정 형식엔 칸이 없다 → selector 를 추가 칸으로 넣는다 (혜정 런타임은 현재 단계 행을 통째로 LLM 에 준다)
  미해결      ①② 의 미해결(업무 · 경로 단위)만 넘긴다. 단계의 가선택 확인 사항은 승인 때 사람이 확인했으므로 뺀다
  도메인      혜정은 단계 도메인 = 업무 도메인을 요구 → 업무 도메인을 경로(그래프)의 도메인으로 맞춘다
  앞 단계 결과 업무가 출발 데이터 조회(우리 0번 단계)로 시작하면, 그 뒤 단계 행에 source_step_id(조회 단계)를 적는다
              → 혜정 dependencies 가 조회 단계에 output_consumers, 뒤 단계에 input_dependencies 를 붙여 Binding 을 만든다
  참조 조회   (2026-11-11) 쓰기에 넣을 코드를 이름으로 찾는 조회 단계 — 그 행에 reference(넣을 이름 · 필드),
              쓰기 행에 reference_sources(조회 단계 · 꺼낼 출력 필드 · 넣을 입력 필드)를 적는다 → dependencies 가 출처마다 관계를 붙인다
  업무 사이   (2026-11-12) ① 의 depends_on → 뒤 업무 첫 단계 행에 source_step_id(앞 업무 마지막 단계)
  행 상태값   (2026-11-11) rowType · rowFlag — 업무 동작으로 정한 값을 row_values 에 → draft_build 가 그 입력을 고정값으로 넣는다
  검토 전     (2026-11-12) 최종 등록 화면은 분석 → IR → 승인 순서 — 승인 없이 만든 초안은 approval_status "review",
              파일 이름 review-<해시>.json. 승인하면 지금처럼 tdg-<해시>.json (approved)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tap.apis.gate import Approval, Gate
from tap.apis.select import ApiSelection
from tap.goal.extract import TaskPlan
from tap.graph.paths import PathPlan


def hyejung_approved(tp: TaskPlan, pp: PathPlan, sel: ApiSelection, gate: Gate, approval: Approval | None,
                     source_files: dict[str, str] | None = None) -> dict[str, Any]:
    """approval 이 없으면 검토 전 초안 (approval_status "review") — IR 을 먼저 만들어 보고 승인한다 (2026-11-12)."""
    status = "approved" if approval else "review"
    domain = {p.sequence: p.domain for p in pp.paths}
    tasks = [{"sequence": t.sequence, "domain": domain.get(t.sequence, t.domain), "action": t.action, "conditions": t.conditions,
              "count": t.count, "origin": t.origin, "constraints": [c.model_dump() for c in t.constraints],
              "depends_on": t.depends_on, "source_phrases": t.source_phrases} for t in tp.tasks]
    rows = []
    for seq in sorted({r.path_sequence for r in sel.api_selection_results}):
        mine = sorted((r for r in sel.api_selection_results if r.path_sequence == seq), key=lambda r: r.step)
        # 뒤 단계가 결과를 넘겨받는 단계: 출발 데이터 조회(0번) 또는 새로 만든 생성 단계(생성 → 수정, 2026-11-12)
        made = 1 if len(mine) > 1 and mine[0].step == 0 and mine[0].kind == "조회" else \
            next((i for i, r in enumerate(mine, 1) if r.kind == "생성" and i < len(mine)), None)
        lookup = f"{seq}-{made}" if made else None
        new_no = {r.step: i for i, r in enumerate(mine, 1)}
        refs: dict[int, list[dict[str, Any]]] = {}               # 쓰기 단계(새 번호) → 그 단계가 쓰는 참조 조회들
        for r in mine:
            if r.reference and r.reference.for_step in new_no:
                ref = r.reference
                refs.setdefault(new_no[ref.for_step], []).append(
                    {"source_step_id": f"{seq}-{new_no[r.step]}", "source_output_names": [ref.output_field or ref.code_field],
                     "input_field": ref.code_field, "term": ref.term, "value": ref.value})
        for i, r in enumerate(mine, 1):
            if r.selected is None:
                raise ValueError(f"단계 {seq}-{r.step} 에 고른 API 가 없어 IR 을 만들 수 없습니다")
            cands = list(dict.fromkeys([r.selected.api_id] + [c.api_id for c in r.api_candidates]))
            rows.append({"path_sequence": seq, "step": i, "domain": domain.get(seq, r.domain), "edge": r.edge,
                         "api_candidates": cands, "selected_api_id": r.selected.api_id, "selector": r.selected.selector,
                         "selection_status": r.selection_status, "selected_by": r.selected_by,
                         "selection_reason": r.selection_reason, "approval_status": status,
                         "source_step": f"{seq}-{r.step}", "kind": r.kind, "from": r.from_, "to": r.to,
                         **({"source_step_id": lookup} if lookup and i > made and not r.reference else {}),
                         **({"reference": {"term": r.reference.term, "value": r.reference.value,      # 조회 요청에 넣을 이름
                                           "name_field": r.reference.name_field, "output_field": r.reference.output_field,
                                           "for_step_id": f"{seq}-{new_no[r.reference.for_step]}"}} if r.reference else {}),
                         **({"reference_sources": refs[i]} if i in refs else {}),
                         **({"row_values": dict(r.row_values)} if r.row_values else {})})
    _link_depends_on(tp, rows)
    unresolved =[{"path_sequence": u.path_sequence, "step": None, "reason": u.reason} for u in sel.unresolved if u.step is None]
    out = {"original_question": tp.original_question, "approval_status": status, "intent_tasks": tasks,
           "api_selection_results": rows, "unresolved": unresolved, "source_files": source_files or {}}
    if approval:
        out["tdg_approval"] = {"selection_hash": approval.selection_hash, "approver": approval.approver, "at": approval.at,
                               "gate_status": gate.status, "scenario": approval.scenario, "steps": approval.steps}
    else:
        out["tdg_review"] = {"selection_hash": gate.selection_hash, "gate_status": gate.status}
    return out


def _link_depends_on(tp: TaskPlan, rows: list[dict[str, Any]]) -> None:
    """업무 사이 결과 넘기기 (2026-11-12) — ① 의 depends_on 을 승인본 행의 source_step_id 로.

    혜정 dependencies 는 업무 조건 문장("1번 업무에서 조회한 …")으로만 업무 사이를 잇는데, ① 은 "1번 업무에서 생성한 상품"처럼 쓴다
    → 못 잇는다. 그래서 depends_on 이 있는 업무의 첫 단계(참조 조회 · 이미 출처가 있는 행 제외)에 앞 업무의 마지막 단계를 적는다.
    앞 업무가 여럿이면 가장 가까운 업무. 꺼낼 출력 이름은 IR 이 정한다.
    """
    last = {}
    for r in rows:
        last[r["path_sequence"]] = f"{r['path_sequence']}-{r['step']}"
    for t in tp.tasks:
        deps = [d for d in t.depends_on if d in last and d < t.sequence]
        if not deps:
            continue
        first = next((r for r in rows if r["path_sequence"] == t.sequence and "reference" not in r), None)
        if first is not None and "source_step_id" not in first:
            first["source_step_id"] = last[max(deps)]


def missing_materials(root: Path, data: dict[str, Any], plan: list[dict[str, Any]]) -> list[str]:
    """IR 생성에 필요한 자료가 있는지 승인 때 미리 본다 (2026-11-05 — 생성 도중 fatal 로 멈추기 전에).

    모든 단계: 요청 스키마(Canonical) · Parameter KB. 출력을 넘겨줘야 하는 단계(output_consumers): Response Outputs.
    """
    from tap.agent.parameter_tools import ParameterTools
    tools = ParameterTools(root, data, defer_optional_errors=True)
    out = []
    for s in plan:
        api, sid = s["selected_api_id"], s["step_id"]
        name = api.rsplit("/", 1)[-1]
        if not tools.records.get(("get_request_schema", api)):
            out.append(f"{sid} {name}: 요청 스키마(Canonical) 없음")
        if not tools.records.get(("get_parameter_knowledge", api)):
            out.append(f"{sid} {name}: Parameter KB 없음")
        if s.get("output_consumers") and not tools.records.get(("get_response_outputs", api)):
            out.append(f"{sid} {name}: 뒤 단계에 넘길 Response Outputs 없음")
    return out


def save_hyejung_approved(root: Path, data: dict[str, Any]) -> str:
    """prototype/approved/tdg-<해시 12자>.json (검토 전 초안은 review-<해시 12자>.json) — 같은 선택 결과면 덮어쓴다. 파일 이름을 돌려준다."""
    prefix, block = ("tdg", data["tdg_approval"]) if "tdg_approval" in data else ("review", data["tdg_review"])
    name = f"{prefix}-{block['selection_hash'].split(':')[1][:12]}.json"
    d = root / "prototype/approved"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return name
