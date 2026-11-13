"""공통 — 서버 확인."""
from __future__ import annotations

from fastapi import APIRouter, Request

from tap.api.deps import state
from tap.api.models import Health, doc

router = APIRouter(prefix="/api/common", tags=["공통"])


@router.get("/health", responses=doc(Health))
def health(request: Request):
    """fake_llm: 가짜 LLM 으로 띄운 서버 (tap.cli serve --fake-llm) — 화면이 표시한다."""
    return {"ok": True, "fake_llm": state(request).llm is not None}

