"""시나리오 실행 — 등록 시나리오 드라이런."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from tap.api import services
from tap.api.deps import json_body, state

router = APIRouter(prefix="/api/run", tags=["시나리오 실행"])


@router.post("/dry-run")
def dry_run(request: Request, body: dict = Depends(json_body)):
    """시나리오마다 실행 확인(승인 · 선택 해시 · 이번 실행 R2 확인 · 재승인 필요) → IR 로 요청을 만들어 data/runs/ 에. 하나라도 안 되면 400."""
    return {"run": services.run_registered(state(request).root, body)}
