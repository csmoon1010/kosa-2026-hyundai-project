"""실행 이력."""
from __future__ import annotations

from fastapi import APIRouter, Request

from tap.api import services
from tap.api.deps import state

router = APIRouter(prefix="/api/history", tags=["실행 이력"])


@router.get("/runs")
def runs(request: Request):
    return {"runs": services.runs_list(state(request).root)}
