"""라우터가 같이 쓰는 것 — 요청 본문 · 앱 상태."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import BaseModel


def dump(body: BaseModel | None) -> dict[str, Any]:
    """요청 모델 → 서비스가 받는 dict. 보낸 칸만 (기본값은 넣지 않는다 — 서비스가 '없음'을 판단). 본문이 없으면 {}."""
    return {} if body is None else body.model_dump(exclude_unset=True)


def state(request: Request):
    """root · llm · pending (tap.api.app.create_app)."""
    return request.app.state
