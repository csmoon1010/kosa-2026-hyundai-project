"""API 요청 · 응답 모델 — OpenAPI(/api/openapi.json) → React TypeScript 타입 (docs/fastapi.md 5단계 · docs/react.md 6절).

- 요청 모델은 검사한다. 알려진 칸 밖의 값도 받아 서비스로 넘긴다 (예: budget 을 보내면 서비스가 거부 — 지금과 같은 동작).
  글자 칸은 null 도 받는다 — 비었는지는 서비스가 판단해 지금과 같은 오류 문구를 낸다. 기본값은 서비스로 넘기지 않는다 (deps.dump).
- 응답 모델은 **문서용** — 라우터가 responses= 로 모양만 알리고, 실행 중 응답을 다시 검사하지 않는다
  (예전 형식으로 저장된 실행 기록 · 등록 기록이 있어도 서버 오류가 나지 않게). 칸 이름 · 값은 지금 응답 그대로다.
- 업무 · 경로 · API 선택 · 게이트 · 승인은 서버가 이미 쓰는 모델을 그대로 쓴다 (칸이 어긋날 일이 없게).
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from tap.apis.gate import Approval, Gate
from tap.apis.select import ApiSelection
from tap.goal.extract import TaskPlan
from tap.graph.paths import PathPlan


class Body(BaseModel):
    """요청 본문 공통 — 알려진 칸 밖의 값도 받는다 (서비스가 판단)."""
    model_config = ConfigDict(extra="allow")


class Doc(BaseModel):
    """응답 문서 공통 — 칸이 더 있어도 된다."""
    model_config = ConfigDict(extra="allow")


# ─── 공통 ───────────────────────────────────────────────────────────────────────────

class ErrorBody(Doc):
    error: str
    refused: bool | None = Field(None, description="승인 · 실행 확인이 모자라 거부")
    missing: list[str] | None = Field(None, description="IR 생성에 필요한 자료가 없음")
    log_file: str | None = None
    log_url: str | None = None
    trace: dict[str, Any] | None = Field(None, description="분석 실패 때의 트레이스")


class Health(Doc):
    ok: bool
    fake_llm: bool = Field(False, description="가짜 LLM 으로 띄운 서버 (테스트 · 화면 개발용)")


class Ok(Doc):
    ok: bool


# ─── 시나리오 등록 ─────────────────────────────────────────────────────────────────────

class AnalyzeRequest(Body):
    utterance: str | None = None
    stop_retry: bool = Field(True, description="중지조건 · 재시도 (끄면 재시도 0회)")


class AnalyzeResult(Doc):
    request: str
    tasks: TaskPlan
    paths: PathPlan
    apis: ApiSelection
    gate: Gate
    trace: dict[str, Any]
    notes: list[str]
    trace_file: str


class StageEvent(Doc):
    """분석 스트림 — 단계를 시작할 때마다."""
    event: Literal["stage"]
    stage: Literal["intent", "paths", "apis"]


class AnalyzeEndEvent(Doc):
    """분석 스트림 — 마지막 줄. done 이면 result 가 AnalyzeResult, error 면 ErrorBody."""
    event: Literal["done", "error"]
    result: AnalyzeResult | ErrorBody


class StepMap(Doc):
    step_id: str = Field(description="IR 단계 번호 (업무마다 1부터)")
    source_step: str = Field(description="③ 의 단계 key (1-0 …)")


class ReviewDraft(Doc):
    filename: str | None
    file: str | None = None
    steps: list[StepMap] = []
    error: str | None = None
    missing: list[str] | None = None


class IrRequest(Body):
    selection_hash: str | None = None
    generation_options: dict[str, bool] | None = Field(None, description="stop_retry · kb_rag · dependency_projection")


class IrResult(Doc):
    ir: dict[str, Any] = Field(description="Scenario IR (tasks[].steps[] · inputs · bindings · unresolved …)")
    file: str | None = None
    usage: dict[str, Any] = {}
    step_previews: dict[str, Any] = {}
    log_file: str | None = None
    log_url: str | None = None


class RegisterIrResult(IrResult):
    review: ReviewDraft


class ReviewDraftEvent(ReviewDraft):
    """등록 IR 스트림 — 첫 줄."""
    event: Literal["review_draft"]


class IrProgressEvent(Doc):
    """IR 생성 진행 — generation_start · scenario_steps · llm_request · tool_result · step_preview … (칸은 이벤트마다 다름)."""
    event: str
    step_id: str | None = None
    step: dict[str, Any] | None = None
    steps: list[dict[str, Any]] | None = None


class GenerationComplete(Doc):
    event: Literal["generation_complete"]
    result: IrResult


class GenerationError(Doc):
    event: Literal["generation_error"]
    error: str
    log_file: str | None = None
    log_url: str | None = None


class ConfirmStep(Doc):
    key: str
    edge: str | None = None


class RegisteredSummary(Doc):
    id: str
    name: str
    utterance: str
    domains: list[str]
    registered_at: str | None = None
    catalog_version: int | None = None
    approver: str | None = None
    steps: int
    irreversible: int
    confirm_steps: list[ConfirmStep] = []


class ScenarioList(Doc):
    scenarios: list[RegisteredSummary]


class RegisterRequest(Body):
    selection_hash: str | None = None
    name: str | None = None
    approver: str | None = None
    steps: list[str] = Field([], description="직접 확인한 단계 key (가선택 · LLM 이 고른 API)")
    review_file: str | None = None
    ir_file: str | None = None


class RegisterResult(Doc):
    scenario: RegisteredSummary
    id: str


class RegisteredRecord(Doc):
    id: str
    format: str
    name: str
    utterance: str
    domains: list[str]
    registered_at: str | None = None
    catalog_version: int | None = None
    approval: Approval
    gate: Gate
    tasks: TaskPlan
    paths: PathPlan
    selection: ApiSelection
    step_map: list[StepMap]
    review_file: str
    ir_file: str
    ir: dict[str, Any]
    trace_file: str | None = None


# ─── 확인용 ─────────────────────────────────────────────────────────────────────────

class ApproveRequest(Body):
    selection_hash: str | None = None
    approver: str | None = None
    scenario: bool = False
    steps: list[str] = []


class ApproveResult(Doc):
    approval: Approval
    file: str
    confirm_steps: list[str]
    ir_handoff: ReviewDraft


class InspectIrRequest(Body):
    approved_filename: str | None = None
    generation_options: dict[str, bool] | None = None
    generation_mode: str | None = Field(None, description="예전 요청 — basic · validated")
    generation_config: dict[str, int] | None = Field(None, description="예전 숫자 설정 (legacy_fixed_v1)")


class ReviewRequest(Body):
    expected_revision: int | None = None
    decisions: list[dict[str, Any]] = []


# ─── 실행 · 이력 ────────────────────────────────────────────────────────────────────────

class DryRunItem(Body):
    id: str
    n: int = 1
    confirm: list[str] = Field([], description="이번 실행에서 확인한 R2 단계 key")


class DryRunRequest(Body):
    items: list[DryRunItem] = []


class RunRow(Doc):
    scenario_id: str | None = None
    name: str | None = None
    count: int | None = None
    confirmed: list[str] = []


class RunCall(Doc):
    scenario: str | None = None
    scenario_id: str | None = None
    k: int | None = None
    step_id: str | None = None
    name: str | None = None
    api_id: str | None = None
    tier: str | None = None
    xml: str | None = None
    inputs: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []


class Run(Doc):
    id: str
    at: str
    kind: str
    rows: list[RunRow]
    calls: list[RunCall]
    unresolved: list[str] = []
    rollback: list[dict[str, Any]] = []


class RunResult(Doc):
    run: Run


class RunList(Doc):
    runs: list[Run]


# ─── 관리자 ──────────────────────────────────────────────────────────────────────────

class GraphSaveRequest(Body):
    yaml: str


class GraphSaveResult(Doc):
    file: str
    kept: list[str]
    backup: str | None


class EdgeQuery(Body):
    name: str | None = None
    from_name: str | None = None
    to_name: str | None = None
    to_code: str | None = None


class LookupQuery(Body):
    state_name: str | None = None
    state_code: str | None = None


class GraphMatchRequest(Body):
    edges: list[EdgeQuery] = []
    lookups: list[LookupQuery] = []
    state_field: str | None = None
    domains: list[str] | None = None
    top: int | None = Field(None, description="후보 수 (기본 3 — 편집기와 같게)")


class MatchCandidate(Doc):
    api_id: str
    api_name: str
    selector: dict[str, str]
    action: str | None = None
    score: float
    reasons: list[str]
    selector_unknown: bool


class MatchResult(Doc):
    status: Literal["찾음", "확인 필요", "없음"]
    candidates: list[MatchCandidate]


class GraphMatchResult(Doc):
    edges: list[MatchResult]
    lookups: list[MatchResult]


# 화면 데이터 (GET /api/admin/{part}) — 옮긴 화면이 쓰는 부분부터 칸을 적는다 (R1: operations · environment)

FieldDigest = tuple[str, Optional[str], str]       # 필드 이름 · 한글 이름(없으면 '' 또는 null) · 예시 값


class OperationDigest(Doc):
    id: str = Field(description="api_id")
    path: str
    sum: str = Field(description="명세의 요약 (API 한글 이름)")
    kind: Literal["read", "write"]
    dom: str
    req: list[FieldDigest] = Field(description="요청 필드 — 입력값 표의 '필드설명' 은 여기 한글 이름")
    res: list[FieldDigest]


class OperationsPart(Doc):
    ops: list[OperationDigest]


class BuildInfo(Doc):
    operations: int
    catalog_version: Optional[int] = Field(None, description="API Catalog 버전 — 등록 시나리오의 버전과 다르면 재승인 필요")
    spec_sources: list[dict[str, Any]] = []
    kinds: dict[str, int] = {}
    domains: dict[str, int] = {}
    review: int = 0


class EnvironmentPart(Doc):
    generated_at: str
    build: BuildInfo
    connections: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    overrides_file: Any = None


DATA_PART_MODELS: dict[str, type[BaseModel]] = {"operations": OperationsPart, "environment": EnvironmentPart}


class RuleRequest(Body):
    place: str | None = None
    doc: str | None = None
    item: str | None = None
    dom: str | None = None
    target: str | None = None
    body: str | None = None


class BaselineRequest(Body):
    api_id: str
    body: dict[str, Any]


class PreprocessingBaselineRequest(Body):
    selected_api_id: str
    values: dict[str, Any]


# ─── 라우터 문서 · 스트림 ───────────────────────────────────────────────────────────────

def doc(model: type[BaseModel] | None = None, *errors: int) -> dict[int | str, dict[str, Any]]:
    """라우터 responses= — 성공 모양(model)과 오류 코드(ErrorBody). 응답을 다시 검사하지는 않는다."""
    out: dict[int | str, dict[str, Any]] = {code: {"model": ErrorBody} for code in errors}
    if model is not None:
        out[200] = {"model": model}
    return out


# 스트림 줄 모양 — OpenAPI components 에 넣고, 스트림 경로의 application/x-ndjson 응답에 이어 붙인다 (app.py)
STREAM_EVENTS = [StageEvent, AnalyzeEndEvent, ReviewDraftEvent, IrProgressEvent, GenerationComplete, GenerationError]
STREAMS = {
    "/api/register/analyze": [StageEvent, AnalyzeEndEvent],
    "/api/register/ir": [ReviewDraftEvent, IrProgressEvent, GenerationComplete, GenerationError],
    "/api/inspect/ir": [IrProgressEvent, GenerationComplete, GenerationError],
}
