"""라우터가 같이 쓰는 것 — 요청 본문 · 앱 상태."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request


async def json_body(request: Request) -> dict[str, Any]:
    """요청 본문 — 지금 화면처럼 JSON 객체(dict)로 받는다. 비어 있으면 {} (pydantic 모델은 React 시작 때, docs/fastapi.md 5단계)."""
    raw = await request.body()
    data = json.loads(raw or b"{}")
    if not isinstance(data, dict):
        raise ValueError("요청은 JSON 객체여야 합니다")
    return data


def state(request: Request):
    """root · llm · pending (tap.api.app.create_app)."""
    return request.app.state
