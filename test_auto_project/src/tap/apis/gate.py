"""도구 권한 등급 · 승인 게이트 — API 선택 결과를 실행하기 전에 사람이 무엇을 승인해야 하는지 코드가 정한다.

등급 (data/config/permissions.yaml)
  R0 조회 · R1 되돌릴 수 있는 쓰기 · R2 되돌릴 수 없는 쓰기 · R3 금지(범위 밖 · 삭제)
승인은 두 번이다.
  등록 때 (approve — 승인본 고정): 계획이 맞는가.
    쓰기가 있으면 시나리오 승인, 사람이 확인하지 않은 선택(가선택 · LLM 이 고른 API)은 그 단계를 직접 확인.
    R3 · 보류(API 없음) · 경로 없음 · 범위 밖 업무는 차단 — 승인할 수 없다.
  실행 때 (assert_executable — 실행할 때마다): 지금 해도 되는가.
    R2 단계는 실행할 때마다 확인한다 (승인본이 여러 번 실행될 수 있고, 등록과 실행 사이에 데이터가 바뀔 수 있어서).
    R1 은 승인본이면 추가 확인 없음, R0 은 자동.
LLM 은 등급 · 승인에 관여하지 않는다. 요청에 "승인 없이 실행해"가 있어도 게이트는 바뀌지 않는다.
승인은 선택 결과의 해시에 묶인다 — 승인 뒤에 API 가 바뀌면 실행이 거부된다.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from tap.apis.select import ApiSelection
from tap.graph.model import NEW, StateGraph
from tap.graph.paths import PathPlan

Tier = Literal["R0", "R1", "R2", "R3"]
Need = Literal["자동", "시나리오 승인", "단계 승인", "차단"]


class GateError(ValueError):
    pass


class StepGate(BaseModel):
    key: str                                    # '업무-단계' (예: 1-2)
    path_sequence: int
    step: int
    kind: str
    edge: str
    api_id: str | None
    selector: dict[str, str]
    tier: Tier | None
    requirement: Need                           # 등록 때 필요한 승인
    confirm_on_run: bool = False                # R2 — 실행할 때마다 확인
    reasons: list[str]


class Gate(BaseModel):
    status: Literal["자동", "승인 필요", "차단", "실행할 것 없음"]
    steps: list[StepGate]
    blocked: list[str]                          # 차단 이유 (업무 · 단계)
    need_scenario: bool
    need_steps: list[str]                       # 등록 때 직접 확인해야 하는 단계 key (가선택 · LLM 선택)
    confirm_steps: list[str] = Field(default_factory=list)   # 실행할 때마다 확인해야 하는 단계 key (R2)
    selection_hash: str


class Approval(BaseModel):
    selection_hash: str
    approver: str
    at: str
    scenario: bool
    steps: list[str] = Field(default_factory=list)


INJECTION_PATTERNS = ["이전 지시", "무시하고", "시스템 지시", "새 규칙", "###", "답하라", "승인 없이", "승인 절차 없이",
                      "승인 단계는 건너"]
FIELD_VALUE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*[=:]\s*\S+")    # '필드=값' 모양 — 사람이 업무를 말할 때는 쓰지 않는다


def load_permissions(path: str | Path | None) -> dict[str, Any]:
    p = Path(path) if path else None
    raw = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p and p.exists() else {}
    return {"allowed_domains": raw.get("allowed_domains") or ["pd", "od", "ds"],
            "forbidden_words": raw.get("forbidden_words") or ["삭제", "delete", "remove", "폐기"],
            "injection_patterns": raw.get("injection_patterns") or INJECTION_PATTERNS}


def _field_names(model: type[BaseModel], seen: set | None = None) -> set[str]:
    """출력 모델의 칸 이름 (안쪽 모델까지)."""
    seen = set() if seen is None else seen
    if model in seen:
        return set()
    seen.add(model)
    names = set(model.model_fields)
    for f in model.model_fields.values():
        for t in [f.annotation, *getattr(f.annotation, "__args__", ())]:
            for x in [t, *getattr(t, "__args__", ())]:
                if isinstance(x, type) and issubclass(x, BaseModel):
                    names |= _field_names(x, seen)
    return names


def system_identifiers(meta: list[dict[str, Any]], graphs: list[StateGraph]) -> dict[str, list[str]]:
    """요청에 나올 일이 없는 우리 시스템 식별자 — API Metadata · 그래프 · 출력 스키마에서 자동으로 뽑는다.

    API 가 늘거나 그래프 · 출력 칸이 바뀌면 감지 목록도 저절로 바뀐다 (손으로 적는 목록이 아님).
    출력 칸은 밑줄이 있는 이름만 — sequence · domain · count 같은 일반 낱말은 정상 요청에도 나온다.
    """
    from tap.goal.extract import TaskPlan
    from tap.graph.paths import PathPlan, choice_schema
    from tap.apis.select import ApiSelection
    out_fields: set[str] = set()
    for m in (TaskPlan, PathPlan, choice_schema(graphs), ApiSelection, Gate):
        out_fields |= _field_names(m)
    return {
        "API 구분값 필드": sorted({s["field"] for m in meta for s in m.get("selectors") or []}),
        "API 이름": sorted({m["operation_id"] for m in meta if m.get("operation_id")}),
        "그래프": sorted({x for g in graphs for x in (g.graph_id, g.state_field) if x}),
        "출력 칸": sorted(n for n in out_fields if "_" in n.strip("_")),
    }


def detect_injections(utterance: str, flagged: list[str], perms: dict[str, Any],
                      known: dict[str, list[str]] | None = None) -> list[str]:
    """요청 속 지시문 감지 — 하나라도 있으면 전체 차단.

    ① LLM 이 적은 지시문(원문에 있는 것만) ② 지시문 낱말(permissions.yaml)
    ③ 우리 시스템 식별자(구분값 필드 · API 이름 · 그래프 · 출력 칸 — system_identifiers) ④ '필드=값' 모양
    ③ ④ 는 특정 API 의 파라미터(procGb 등)를 손으로 적지 않고, 업무를 말하는 사람은 쓰지 않는 말로 잡는다.
    """
    hits = [f"LLM 이 지시문으로 봄: '{x}'" for x in flagged]
    low = utterance.lower()
    hits += [f"지시문 패턴 '{w}'" for w in perms["injection_patterns"] if w.lower() in low]
    for kind, words in (known or {}).items():
        hits += [f"시스템 식별자 · {kind} '{w}'" for w in words
                 if re.search(rf"(?<![A-Za-z0-9_]){re.escape(w)}(?![A-Za-z0-9_])", utterance, re.IGNORECASE)]
    hits += [f"'필드=값' 모양 '{m}'" for m in FIELD_VALUE.findall(utterance)]
    return hits


def detect_in_values(value: Any, perms: dict[str, Any]) -> list[str]:
    """사람이 직접 넣는 값(혜정 화면의 Baseline 등록값 · IR 검토 입력값)의 지시문 — 지시문 낱말만 본다.

    값에는 코드 · 식별자 · 'a=b' 같은 문자열이 정상으로 들어갈 수 있어 시스템 식별자 · '필드=값' 모양은 보지 않는다.
    """
    texts: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            texts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(value)
    return [f"지시문 패턴 '{w}' ({t[:40]})" for t in texts for w in perms["injection_patterns"] if w.lower() in t.lower()]


def blocked_gate(sel: ApiSelection, reasons: list[str]) -> Gate:
    """요청 전체를 차단하는 게이트 (인젝션 감지) — 승인으로도 열 수 없다."""
    return Gate(status="차단", steps=[], blocked=[f"요청 속 지시문 감지 — 전체 차단 ({r})" for r in reasons],
                need_scenario=False, need_steps=[], confirm_steps=[], selection_hash=selection_hash(sel))


def base_tier(meta: dict[str, Any] | None, perms: dict[str, Any]) -> tuple[Tier, list[str]]:
    """API 만 보고 정하는 기본 등급 (Tool Registry 에도 같은 값)."""
    if not meta:
        return "R3", ["API Metadata 에 없음"]
    text = f"{meta.get('api_name') or ''} {meta.get('operation_id') or ''} {meta['api_id']}".lower()
    hit = [w for w in perms["forbidden_words"] if w.lower() in text]
    if hit:
        return "R3", [f"금지 낱말 {hit}"]
    if meta.get("domain") not in perms["allowed_domains"]:
        return "R3", [f"1차 범위 밖 도메인 {meta.get('domain')}"]
    if meta.get("kind") == "read":
        return "R0", ["조회"]
    if meta.get("irreversible") == "불가":
        return "R2", ["되돌릴 수 없는 API (Metadata irreversible 불가)"]
    return "R1", ["쓰기"]


def _way_back(g: StateGraph, frm: str, to: str) -> bool:
    """도착 상태에서 출발 상태로 API 화살표만으로 돌아갈 수 있는지 — 되돌릴 수 있는 쓰기인지."""
    if frm == NEW:
        return False
    seen, q = {to}, deque([to])
    while q:
        c = q.popleft()
        if c == frm:
            return True
        for e in g.out_edges(c):
            if e.to_code not in seen:
                seen.add(e.to_code)
                q.append(e.to_code)
    return False


def selection_hash(sel: ApiSelection) -> str:
    rows = [(r.path_sequence, r.step, r.kind, r.selected.api_id if r.selected else None,
             r.selected.selector if r.selected else None) for r in sel.api_selection_results]
    return "sha256:" + hashlib.sha256(json.dumps([sel.original_question, rows], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def gate_for(sel: ApiSelection, pp: PathPlan, graphs: list[StateGraph], metadata: list[dict[str, Any]],
             perms: dict[str, Any]) -> Gate:
    meta = {m["api_id"]: m for m in metadata}
    by_id = {g.graph_id: g for g in graphs}
    paths = {p.sequence: p for p in pp.paths}
    blocked: list[str] = []
    for p in pp.paths:
        if p.domain.lower() not in perms["allowed_domains"]:
            blocked.append(f"{p.sequence}번 업무: 1차 범위 밖 도메인 {p.domain} (R3)")
        if p.status == "경로 없음":
            blocked.append(f"{p.sequence}번 업무: 경로 없음")
    steps: list[StepGate] = []
    for r in sel.api_selection_results:
        key = f"{r.path_sequence}-{r.step}"
        api = r.selected.api_id if r.selected else None
        reasons: list[str] = []
        if r.selected is None:
            tier, need = None, "차단"
            reasons.append("API 없음 (보류)")
        else:
            tier, reasons = base_tier(meta.get(api), perms)
            p = paths.get(r.path_sequence)
            if p and p.domain.lower() not in perms["allowed_domains"]:
                tier, reasons = "R3", reasons + [f"업무 도메인 {p.domain} 이 1차 범위 밖"]
            if tier == "R1":
                g = by_id.get(p.graph_id or "") if p else None
                if r.kind == "수정" or g is None:
                    tier, reasons = "R2", reasons + ["그래프 없는 수정 — 되돌리는 방법을 모름"]
                elif r.kind == "상태변경":
                    a = NEW if r.from_ == NEW else g.code_of(r.from_ or "")
                    b = g.code_of(r.to or "")
                    if a and b and not _way_back(g, a, b):
                        tier, reasons = "R2", reasons + [f"{r.to} 에서 {r.from_} 로 돌아가는 화살표 없음"]
                    else:
                        reasons.append(f"{r.to} → {r.from_} 로 되돌릴 수 있음")
            need = {"R0": "자동", "R1": "시나리오 승인", "R2": "시나리오 승인", "R3": "차단"}[tier]
            if tier == "R2":
                reasons.append("되돌릴 수 없음 — 실행할 때마다 확인")
            if need in ("자동", "시나리오 승인") and (r.selection_status == "가선택" or r.selected_by == "LLM"):
                need = "단계 승인"
                reasons.append(f"사람이 확인하지 않은 선택 ({r.selection_status} · {r.selected_by}) — API 가 맞는지 확인")
        if need == "차단":
            blocked.append(f"{key} '{r.edge}': " + "; ".join(reasons))
        steps.append(StepGate(key=key, path_sequence=r.path_sequence, step=r.step, kind=r.kind, edge=r.edge, api_id=api,
                              selector=r.selected.selector if r.selected else {}, tier=tier, requirement=need,
                              confirm_on_run=tier == "R2", reasons=reasons))
    need_steps = [s.key for s in steps if s.requirement == "단계 승인"]
    need_scenario = any(s.requirement in ("시나리오 승인", "단계 승인") for s in steps)
    status = "차단" if blocked else "실행할 것 없음" if not steps else "승인 필요" if need_scenario else "자동"
    return Gate(status=status, steps=steps, blocked=list(dict.fromkeys(blocked)), need_scenario=need_scenario,
                need_steps=need_steps, confirm_steps=[s.key for s in steps if s.confirm_on_run], selection_hash=selection_hash(sel))


def approve(gate: Gate, approver: str, scenario: bool = False, steps: list[str] | tuple[str, ...] = ()) -> Approval:
    """등록 때 승인 (승인본 고정). 차단이면 승인할 수 없고, 모자라면 무엇이 모자란지 알려 준다."""
    if gate.status == "차단":
        raise GateError("차단된 것이 있어 승인할 수 없습니다: " + " / ".join(gate.blocked))
    missing = (["시나리오 승인"] if gate.need_scenario and not scenario else []) + \
        [f"단계 {k} 승인" for k in gate.need_steps if k not in steps]
    if missing:
        raise GateError("승인이 모자랍니다: " + ", ".join(missing))
    return Approval(selection_hash=gate.selection_hash, approver=approver,
                    at=datetime.now().astimezone().isoformat(timespec="seconds"), scenario=scenario, steps=list(steps))


def assert_executable(sel: ApiSelection, gate: Gate, approval: Approval | None,
                      confirm: list[str] | tuple[str, ...] = ()) -> None:
    """실행 직전 확인 — 실행기는 이것을 통과해야만 API 를 부른다. confirm: 이번 실행에서 확인한 R2 단계 key."""
    if gate.status == "차단":
        raise GateError("차단된 시나리오는 실행할 수 없습니다")
    if gate.status == "자동":
        return
    if approval is None:
        raise GateError("승인 없이 실행할 수 없습니다 — 필요한 승인: " + ", ".join(
            (["시나리오"] if gate.need_scenario else []) + [f"단계 {k}" for k in gate.need_steps]))
    if approval.selection_hash != selection_hash(sel) or approval.selection_hash != gate.selection_hash:
        raise GateError("승인한 뒤 선택 결과가 바뀌었습니다 — 다시 승인하세요")
    approve(gate, approval.approver, approval.scenario, approval.steps)     # 승인 내용이 지금 게이트를 만족하는지 다시 확인
    missing = [k for k in gate.confirm_steps if k not in confirm]
    if missing:
        raise GateError("실행할 때 확인이 필요합니다 (되돌릴 수 없는 호출): " + ", ".join(f"단계 {k}" for k in missing)
                        + " — 승인본 승인과 별개로 실행할 때마다 확인")


def dry_run(sel: ApiSelection, gate: Gate, approval: Approval | None,
            confirm: list[str] | tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """드라이런 — 실행 확인을 통과하면 부를 순서만 돌려준다 (실제 호출은 하지 않음)."""
    assert_executable(sel, gate, approval, confirm)
    return [{"key": s.key, "kind": s.kind, "edge": s.edge, "api_id": s.api_id, "selector": s.selector, "tier": s.tier}
            for s in gate.steps]
