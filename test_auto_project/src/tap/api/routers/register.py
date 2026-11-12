"""시나리오 등록 — 분석(①②③) → 시나리오 생성(IR) → 승인 · 등록 · 등록 시나리오."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from tap.api import services
from tap.api.deps import json_body, state
from tap.api.streaming import ndjson, wants_stream

router = APIRouter(prefix="/api/register", tags=["시나리오 등록"])


def _json(code: int, body: dict[str, Any]):
    from tap.api.app import JSON
    return JSON(body, status_code=code)


@router.post("/analyze")
def analyze(request: Request, body: dict = Depends(json_body)):
    """① 요청 이해 → ② 경로 → ③ API 선택 → 권한 등급 · 승인 게이트. 결과는 서버 메모리(pending)에.
    Accept: application/x-ndjson 이면 단계 시작마다 {"event":"stage","stage":…}, 마지막 {"event":"done"|"error","result":…}."""
    st = state(request)
    if not wants_stream(request):
        return _json(*services.analyze(st.root, st.llm, st.pending, body))
    if not str(body.get("utterance") or "").strip():
        raise ValueError("자연어 요청이 비어 있습니다")

    def work(emit):
        code, result = services.analyze(st.root, st.llm, st.pending, body, on_stage=lambda s: emit({"event": "stage", "stage": s}))
        emit({"event": "done" if code == 200 else "error", "result": result})
    return ndjson(work)


@router.post("/ir")
def ir(request: Request, body: dict = Depends(json_body)):
    """검토 초안(data/ir_inputs/review-*.json)을 만들고 바로 IR 을 생성한다. 게이트 차단 · 자료 부족이면 400.
    스트림이면 첫 줄 {"event":"review_draft",…} → IR 진행 → {"event":"generation_complete"|"generation_error",…}."""
    st = state(request)
    mode = services.check_ir_request(body)
    code, review = services.review_draft(st.root, st.pending, body)
    if code != 200:
        return _json(code, review)
    ir_body = {"approved_filename": review["filename"]}
    if wants_stream(request):
        return ndjson(lambda emit: services.generate_ir_stream(st.root, ir_body, mode, emit),
                      first=[{"event": "review_draft", **review}])
    return {"review": review, **services.generate_ir(st.root, ir_body, mode)}


@router.get("/scenarios")
def scenarios(request: Request):
    """등록 시나리오 목록 (요약, 최신순)."""
    return {"scenarios": services.registered_list(state(request).root)}


@router.post("/scenarios")
def register_scenario(request: Request, body: dict = Depends(json_body)):
    """승인하고 등록 — 서버가 계산한 게이트로 승인, 검토 초안 · IR 이 이 분석 결과로 만든 것인지 확인. 모자라면 400 refused."""
    st = state(request)
    return _json(*services.register(st.root, st.pending, body))


@router.get("/scenarios/{scenario_id}")
def scenario(request: Request, scenario_id: str):
    try:
        return services.registered_get(state(request).root, scenario_id)
    except ValueError as e:
        return _json(404, {"error": str(e)})


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(request: Request, scenario_id: str):
    try:
        services.registered_delete(state(request).root, scenario_id)
    except ValueError as e:
        return _json(404, {"error": str(e)})
    return {"ok": True}
