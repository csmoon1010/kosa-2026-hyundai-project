"""공통 — 서버 확인 · 화면 데이터."""
from __future__ import annotations

from fastapi import APIRouter, Request

from tap.api.deps import state
from tap.ui.export import ui_data

router = APIRouter(prefix="/api/common", tags=["공통"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/data")
def data(request: Request):
    """화면 데이터 JSON (React 용). 지금 화면은 /tap-data.js."""
    return ui_data(state(request).root)
