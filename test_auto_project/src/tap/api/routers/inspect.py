"""시나리오 등록(확인용) — 승인, 저장된 승인본으로 IR 생성 · 로그 · 예산 · IR 입력 검토 (IR 부분은 혜정 코드에서 옮김)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from tap.api import services
from tap.api.deps import dump, ir_mode, state
from tap.api.models import ApproveRequest, ApproveResult, InspectIrRequest, IrResult, ReviewRequest, doc
from tap.api.streaming import ndjson, wants_stream

router = APIRouter(prefix="/api/inspect", tags=["시나리오 등록(확인용)"])


def _json(code: int, body):
    from tap.api.app import JSON
    return JSON(body, status_code=code)


@router.post("/approve", responses=doc(ApproveResult, 400))
def approve(request: Request, req: ApproveRequest | None = None):
    """승인 — 승인 기록(data/approved/) + IR 생성 입력(data/ir_inputs/tdg-*.json). 모자라면 400 refused."""
    st = state(request)
    return _json(*services.approve(st.root, st.pending, dump(req)))


@router.post("/ir", responses=doc(IrResult, 400))
def ir(request: Request, req: InspectIrRequest | None = None):
    """저장된 승인본(approved_filename)으로 IR 생성. 스트림 지원. budget · budget_policy 를 보내면 400."""
    root = state(request).root
    body = dump(req)
    mode = ir_mode(request, body)
    if wants_stream(request):
        return ndjson(lambda emit: services.generate_ir_stream(root, body, mode, emit))
    return services.generate_ir(root, body, mode)


@router.get("/ir/approved")
def approved(request: Request):
    return services.approved_selections(state(request).root)


@router.get("/ir/budget", responses=doc(None, 400))
def budget(request: Request, filename: str = ""):
    try:
        return services.ir_budget(state(request).root, filename)
    except (ValueError, OSError, KeyError) as error:
        return _json(400, {"error": str(error)})


@router.get("/ir/logs")
def logs(request: Request):
    return {"runs": services.scenario_ir_log_summaries(state(request).root)}


@router.get("/ir/logs/{name}", responses=doc(None, 404))
def log_file(request: Request, name: str):
    file = services.ir_log_file(state(request).root, name)
    if file is None:
        return _json(404, {"error": "로그 파일이 없습니다"})
    return Response(file.read_bytes(), media_type="application/x-ndjson; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/ir/reviews")
def reviews(request: Request):
    from tap.ir.input_review import list_reviews
    return {"reviews": list_reviews(state(request).root)}


@router.get("/ir/reviews/{scenario_id}")
def review(request: Request, scenario_id: str):
    from tap.ir.input_review import load
    return load(state(request).root, scenario_id)


@router.post("/ir/reviews/{scenario_id}/decisions", responses=doc(None, 400, 409))
def decisions(request: Request, scenario_id: str, req: ReviewRequest | None = None):
    """입력 결정 저장 — 값에서 지시문 검사. 충돌 409."""
    from tap.ir.input_review import submit
    root, body = state(request).root, dump(req)
    services.guard_human_values(root, body.get("decisions"))
    return submit(root, scenario_id, body, confirm=False)


@router.post("/ir/reviews/{scenario_id}/confirm", responses=doc(None, 400, 409))
def confirm(request: Request, scenario_id: str, req: ReviewRequest | None = None):
    from tap.ir.input_review import submit
    root, body = state(request).root, dump(req)
    services.guard_human_values(root, body.get("decisions"))
    return submit(root, scenario_id, body, confirm=True)
