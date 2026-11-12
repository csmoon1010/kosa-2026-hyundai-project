"""실행 이력."""
from __future__ import annotations

from fastapi import APIRouter, Request

from tap.api import services
from tap.api.deps import state
from tap.api.models import RunList, doc

router = APIRouter(prefix="/api/history", tags=["실행 이력"])


@router.get("/runs", responses=doc(RunList))
def runs(request: Request):
    return {"runs": services.runs_list(state(request).root)}
