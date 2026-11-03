"""①②③ + 승인 → 혜정 IR 초안 생성의 입력(승인본 JSON). 혜정 코드는 고치지 않고 형식만 맞춘다.

혜정 쪽(tap.ir.draft_build)은 prototype/approved/<파일>.json 을 읽어 Baseline · Parameter KB 참조 → 입력값 매핑 →
Output Binding → Scenario IR 초안을 만든다. 우리 승인(/api/approve)이 성공했을 때만 이 파일을 만든다.

형식을 맞추는 곳 (2026-11-03 지은 결정)
  단계 번호   혜정은 1 이상만 받는다 → 업무마다 1부터 다시 매기고, 우리 단계 key(1-0 …)는 source_step 에 남긴다
  구분값      혜정 형식엔 칸이 없다 → selector 를 추가 칸으로 넣는다 (혜정 런타임은 현재 단계 행을 통째로 LLM 에 준다)
  미해결      ①② 의 미해결(업무 · 경로 단위)만 넘긴다. 단계의 가선택 확인 사항은 승인 때 사람이 확인했으므로 뺀다
  도메인      혜정은 단계 도메인 = 업무 도메인을 요구 → 업무 도메인을 경로(그래프)의 도메인으로 맞춘다
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tap.apis.gate import Approval, Gate
from tap.apis.select import ApiSelection
from tap.goal.extract import TaskPlan
from tap.graph.paths import PathPlan


def hyejung_approved(tp: TaskPlan, pp: PathPlan, sel: ApiSelection, gate: Gate, approval: Approval,
                     source_files: dict[str, str] | None = None) -> dict[str, Any]:
    domain = {p.sequence: p.domain for p in pp.paths}
    tasks = [{"sequence": t.sequence, "domain": domain.get(t.sequence, t.domain), "action": t.action, "conditions": t.conditions,
              "count": t.count, "origin": t.origin, "constraints": [c.model_dump() for c in t.constraints],
              "depends_on": t.depends_on, "source_phrases": t.source_phrases} for t in tp.tasks]
    rows = []
    for seq in sorted({r.path_sequence for r in sel.api_selection_results}):
        mine = sorted((r for r in sel.api_selection_results if r.path_sequence == seq), key=lambda r: r.step)
        for i, r in enumerate(mine, 1):
            if r.selected is None:
                raise ValueError(f"단계 {seq}-{r.step} 에 고른 API 가 없어 IR 을 만들 수 없습니다")
            cands = list(dict.fromkeys([r.selected.api_id] + [c.api_id for c in r.api_candidates]))
            rows.append({"path_sequence": seq, "step": i, "domain": domain.get(seq, r.domain), "edge": r.edge,
                         "api_candidates": cands, "selected_api_id": r.selected.api_id, "selector": r.selected.selector,
                         "selection_status": r.selection_status, "selected_by": r.selected_by,
                         "selection_reason": r.selection_reason, "approval_status": "approved",
                         "source_step": f"{seq}-{r.step}", "kind": r.kind, "from": r.from_, "to": r.to})
    unresolved = [{"path_sequence": u.path_sequence, "step": None, "reason": u.reason} for u in sel.unresolved if u.step is None]
    return {"original_question": tp.original_question, "approval_status": "approved", "intent_tasks": tasks,
            "api_selection_results": rows, "unresolved": unresolved, "source_files": source_files or {},
            "tdg_approval": {"selection_hash": approval.selection_hash, "approver": approval.approver, "at": approval.at,
                             "gate_status": gate.status, "scenario": approval.scenario, "steps": approval.steps}}


def save_hyejung_approved(root: Path, data: dict[str, Any]) -> str:
    """prototype/approved/tdg-<해시 12자>.json — 같은 선택 결과를 다시 승인하면 덮어쓴다. 파일 이름을 돌려준다."""
    name = f"tdg-{data['tdg_approval']['selection_hash'].split(':')[1][:12]}.json"
    d = root / "prototype/approved"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return name
