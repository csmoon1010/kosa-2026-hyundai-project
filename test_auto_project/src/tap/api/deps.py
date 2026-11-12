"""라우터가 같이 쓰는 것 — 요청 본문 · 앱 상태."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import BaseModel


def dump(body: BaseModel | None) -> dict[str, Any]:
    """요청 모델 → 서비스가 받는 dict. 보낸 칸만 (기본값은 넣지 않는다 — 서비스가 '없음'을 판단). 본문이 없으면 {}."""
    return {} if body is None else body.model_dump(exclude_unset=True)


def state(request: Request):
    """root · llm · ir_runtime · pending (tap.api.app.create_app)."""
    return request.app.state


def ir_mode(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """IR 생성 인자 — 생성 옵션 검사 결과 + (가짜로 띄웠으면) 가짜 런타임."""
    from tap.api.services import check_ir_request
    mode = check_ir_request(body)
    runtime = request.app.state.ir_runtime
    return {**mode, "runtime_factory": runtime} if runtime else mode
