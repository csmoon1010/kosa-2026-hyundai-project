"""진행 스트림(NDJSON) — 작업을 스레드에서 돌리고, 진행 이벤트를 큐로 받아 한 줄씩 바로 보낸다 (docs/fastapi.md 4 · 6.1).

작업(분석 · IR 생성)은 동기 코드라 별도 스레드에서 돈다. 작업이 emit(event) 를 부를 때마다 큐에 넣고,
응답은 큐에서 꺼내는 대로 보낸다 — 끝까지 모았다가 한꺼번에 보내지 않는다. 화면이 연결을 끊어도 작업은 끝까지 돈다.
"""
from __future__ import annotations

import json
import queue
import threading
from typing import Any, Callable, Iterator

from fastapi import Request
from fastapi.responses import StreamingResponse

_DONE = object()
HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


def wants_stream(request: Request) -> bool:
    return "application/x-ndjson" in request.headers.get("accept", "")


def ndjson(work: Callable[[Callable[[dict[str, Any]], None]], None], first: list[dict[str, Any]] | None = None) -> StreamingResponse:
    """work(emit) 를 스레드에서 돌린다. first 는 작업 전에 먼저 보낼 줄. 작업이 예외를 내면 마지막 줄로 error 를 보낸다."""
    q: queue.Queue = queue.Queue()
    for event in first or []:
        q.put(event)

    def runner() -> None:
        try:
            work(q.put)
        except Exception as error:          # 작업이 스스로 오류 줄을 못 보낸 경우
            q.put({"event": "error", "result": {"error": f"{type(error).__name__}: {error}"}})
        finally:
            q.put(_DONE)

    threading.Thread(target=runner, daemon=True).start()

    def lines() -> Iterator[bytes]:
        while True:
            item = q.get()
            if item is _DONE:
                return
            yield (json.dumps(item, ensure_ascii=False, default=str) + "\n").encode("utf-8")

    return StreamingResponse(lines(), media_type="application/x-ndjson; charset=utf-8", headers=HEADERS)
