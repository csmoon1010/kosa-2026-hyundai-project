"""시나리오 등록 — 분석(①②③) → 시나리오 생성(IR) → 승인 · 등록 · 등록 시나리오."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from tap.api import services
from tap.api.deps import dump, ir_mode, state
from tap.api.models import (AnalyzeRequest, AnalyzeResult, IrRequest, Ok, RegisteredRecord, RegisterIrResult,
                            RegisterRequest, RegisterResult, ScenarioList, doc)
from tap.api.streaming import ndjson, wants_stream

router = APIRouter(prefix="/api/register", tags=["시나리오 등록"])


def _json(code: int, body: dict[str, Any]):
    from tap.api.app import JSON
    return JSON(body, status_code=code)


@router.post("/analyze", responses=doc(AnalyzeResult, 400))
def analyze(request: Request, req: AnalyzeRequest | None = None):
    """① 요청 이해 → ② 경로 → ③ API 선택 → 권한 등급 · 승인 게이트. 결과는 서버 메모리(pending)에.
    Accept: application/x-ndjson 이면 단계 시작마다 {"event":"stage","stage":…}, 마지막 {"event":"done"|"error","result":…}."""
    st = state(request)
    body = dump(req)
    if not wants_stream(request):
        return _json(*services.analyze(st.root, st.llm, st.pending, body))
    if not str(body.get("utterance") or "").strip():
        raise ValueError("자연어 요청이 비어 있습니다")

    def work(emit):
        code, result = services.analyze(st.root, st.llm, st.pending, body, on_stage=lambda s: emit({"event": "stage", "stage": s}))
        emit({"event": "done" if code == 200 else "error", "result": result})
    return ndjson(work)


@router.post("/ir", responses=doc(RegisterIrResult, 400))
def ir(request: Request, req: IrRequest | None = None):
    """검토 초안(data/ir_inputs/review-*.json)을 만들고 바로 IR 을 생성한다. 게이트 차단 · 자료 부족이면 400.
    스트림이면 첫 줄 {"event":"review_draft",…} → IR 진행 → {"event":"generation_complete"|"generation_error",…}."""
    st = state(request)
    body = dump(req)
    mode = ir_mode(request, body)
    code, review = services.review_draft(st.root, st.pending, body)
    if code != 200:
        return _json(code, review)
    ir_body = {"approved_filename": review["filename"]}
    if wants_stream(request):
        return ndjson(lambda emit: services.generate_ir_stream(st.root, ir_body, mode, emit),
                      first=[{"event": "review_draft", **review}])
    return {"review": review, **services.generate_ir(st.root, ir_body, mode)}


@router.get("/scenarios", responses=doc(ScenarioList))
def scenarios(request: Request):
    """등록 시나리오 목록 (요약, 최신순)."""
    return {"scenarios": services.registered_list(state(request).root)}


@router.post("/scenarios", responses=doc(RegisterResult, 400))
def register_scenario(request: Request, req: RegisterRequest | None = None):
    """승인하고 등록 — 서버가 계산한 게이트로 승인, 검토 초안 · IR 이 이 분석 결과로 만든 것인지 확인. 모자라면 400 refused."""
    st = state(request)
    return _json(*services.register(st.root, st.pending, dump(req)))


@router.get("/scenarios/{scenario_id}", responses=doc(RegisteredRecord, 404))
def scenario(request: Request, scenario_id: str):
    try:
        return services.registered_get(state(request).root, scenario_id)
    except ValueError as e:
        return _json(404, {"error": str(e)})


@router.delete("/scenarios/{scenario_id}", responses=doc(Ok, 404))
def delete_scenario(request: Request, scenario_id: str):
    try:
        services.registered_delete(state(request).root, scenario_id)
    except ValueError as e:
        return _json(404, {"error": str(e)})
    return {"ok": True}
