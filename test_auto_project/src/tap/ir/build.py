"""Scenario IR — 초안 (문혜정과 형식 합의 전).

등록 결과를 담는 JSON. 경로 계산 결과(Path)를 실행 단계로 펼친다.
  step 1    조회 — 시작 상태의 기존 데이터를 찾는다 (서버가 마지막 상태로 걸러 줌)
  step 2~   쓰기 — 간선마다 API + 고정 선택값. 키 필드는 step 1 응답에서 같은 이름으로 받는다
  verify    조회 — 같은 키로 다시 찾아 마지막 상태가 목표인지 확인

파라미터 출처
  fixed       간선의 선택값 (procGb 등) — 무엇도 덮어쓰지 못함
  bind        앞 호출 응답 (같은 이름 필드)
  run_input   실행할 때 사람이 넣는 값 (협력사코드 · 조회 기간)
  unresolved  아직 정하지 못한 값 — Parameter KB · Baseline 에서 채울 자리 (문혜정)
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from tap.graph.model import Edge, StateGraph
from tap.graph.plan import Goal, Path, PlanResult

IR_VERSION = "0.1-draft"
RUN_INPUTS = {"venCd": "협력사코드", "ven2Cd": "2차협력사코드",
              "fromDate": "조회 시작일 (기본: 7일 전)", "toDate": "조회 종료일 (기본: 오늘)"}


class Param(BaseModel):
    source: Literal["fixed", "bind", "run_input", "unresolved", "empty"]
    value: str | None = None                    # fixed
    ref: str | None = None                      # bind: step1.ordNo
    label: str | None = None


class Step(BaseModel):
    no: int
    kind: Literal["lookup", "call", "verify"]
    api_id: str
    name: str
    selector: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Param] = Field(default_factory=dict)
    for_each: str | None = None                 # 'step1.rows' — 고른 건마다 반복
    pick: int | None = None                     # lookup: 몇 건 고를지
    outputs: list[str] = Field(default_factory=list)
    expect_state: str | None = None
    compensate_with: str | None = None          # 되돌리는 간선 id — 없으면 되돌림 불가
    requires_approval: bool = False


class PlanSummary(BaseModel):
    strategy: str
    start: str
    states: list[str]
    edges: list[str]
    writes: int


class ScenarioIR(BaseModel):
    ir_version: str = IR_VERSION
    status: Literal["ok", "rejected"]
    request: str
    goal: Goal
    graph_id: str
    catalog_version: int | None = None
    plan: PlanSummary | None = None
    steps: list[Step] = Field(default_factory=list)
    alternative: PlanSummary | None = None      # B 안내 — 실행 단계는 등록 때 다시 만든다
    run_inputs: dict[str, str] = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    reason: str | None = None


def _summary(p: Path) -> PlanSummary:
    return PlanSummary(strategy=p.strategy, start=p.start, states=p.states, edges=[e.id for e in p.edges],
                       writes=p.writes)


def _labels(op: dict[str, Any]) -> dict[str, str]:
    return {f["name"]: f.get("label") or f["name"] for f in op["request_fields"]}


def build_ir(request: str, goal: Goal, graph: StateGraph, result: PlanResult,
             operations: list[dict[str, Any]], metadata: list[dict[str, Any]],
             catalog_version: int | None = None) -> ScenarioIR:
    ir = ScenarioIR(status=result.status, request=request, goal=goal, graph_id=graph.graph_id,
                    catalog_version=catalog_version, reason=result.reason)
    if result.status != "ok" or not result.primary:
        return ir

    ops = {o["api_id"]: o for o in operations}
    meta = {m["api_id"]: m for m in metadata}
    p = result.primary
    ir.plan = _summary(p)
    ir.alternative = _summary(result.alternative) if result.alternative else None

    # step 1 — 시작 상태 데이터 조회
    lk_op = ops[p.lookup.api_id]
    resp_names = {f["name"] for f in lk_op["response_fields"]}
    later_req = {f["name"] for e in p.edges for f in ops[e.api_id]["request_fields"]}
    outputs = sorted(resp_names & (later_req | set(graph.verify_key_fields)))
    lookup_params: dict[str, Param] = {}
    for f in lk_op["request_fields"]:
        n = f["name"]
        if n in p.lookup.selector:
            lookup_params[n] = Param(source="fixed", value=p.lookup.selector[n], label=f.get("label"))
        elif n in RUN_INPUTS:
            lookup_params[n] = Param(source="run_input", label=RUN_INPUTS[n])
        else:
            lookup_params[n] = Param(source="empty", label=f.get("label"))
    start = graph.node(p.start)
    steps = [Step(no=1, kind="lookup", api_id=p.lookup.api_id, name=f"{start.name}({start.code}) {graph.entity} 조회",
                  selector=p.lookup.selector, params=lookup_params, pick=goal.count, outputs=outputs,
                  expect_state=p.start)]

    # step 2~ — 간선마다 쓰기 호출
    unresolved: list[str] = []
    for e in p.edges:
        op, labels = ops[e.api_id], _labels(ops[e.api_id])
        params: dict[str, Param] = {}
        for n, label in labels.items():
            if n in e.selector:
                params[n] = Param(source="fixed", value=e.selector[n], label=label)
            elif n in outputs:
                params[n] = Param(source="bind", ref=f"step1.{n}", label=label)
            elif n in RUN_INPUTS:
                params[n] = Param(source="run_input", label=RUN_INPUTS[n])
            else:
                params[n] = Param(source="unresolved", label=label)
                unresolved.append(f"{e.name}: {n}({label})")
        back = next((r for r in graph.edges if r.kind == "api" and r.from_code == e.to_code
                     and r.to_code == e.from_code), None)
        steps.append(Step(no=len(steps) + 1, kind="call", api_id=e.api_id, name=e.name, selector=e.selector,
                          params=params, for_each="step1.rows", expect_state=e.to_code,
                          compensate_with=back.id if back else None,
                          requires_approval=meta.get(e.api_id, {}).get("kind") == "write"))

    # verify — 같은 키로 다시 찾아 마지막 상태 확인
    target = graph.node(goal.target)
    if target.lookup:
        vparams = {n: Param(source="fixed", value=v) for n, v in target.lookup.selector.items()}
        vparams.update({k: Param(source="bind", ref=f"step1.{k}") for k in graph.verify_key_fields})
        steps.append(Step(no=len(steps) + 1, kind="verify", api_id=target.lookup.api_id,
                          name=f"{target.name}({target.code}) 도달 확인 — {graph.state_field} = {target.code}",
                          selector=target.lookup.selector, params=vparams, for_each="step1.rows",
                          expect_state=target.code))

    ir.steps = steps
    ir.run_inputs = {k: v for k, v in RUN_INPUTS.items()
                     if any(s.params.get(k) and s.params[k].source == "run_input" for s in steps)}
    ir.unresolved = list(dict.fromkeys(unresolved))
    ir.requires_approval = any(s.requires_approval for s in steps)
    return ir
