"""FastAPI 앱 — 화면(web/)과 API 를 한 서버가 내려준다 (docs/fastapi.md).

    .venv/bin/python -m tap.cli serve        → http://127.0.0.1:8765/

경로는 메뉴 이름 기준 — /api/register(시나리오 등록) · /api/inspect(확인용) · /api/run(실행) · /api/history(실행 이력) ·
/api/admin(관리자) · /api/common(공통). 오류 응답은 {"error": …} (입력 · 검사 오류 400 · 검토 충돌 409 · 없음 404 · 그 밖 500).
라우터는 일반 함수(def) — LLM 호출 · 파일 쓰기가 동기 코드라 스레드풀에서 돈다. API 목록: /api/docs
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from tap.api import services
from tap.api.routers import admin, common, history, inspect, register, run
from tap.ui.export import ui_data


class JSON(JSONResponse):
    """지금 화면과 같은 JSON — 한글 그대로, 직렬화 못 하는 값(경로 · 시각)은 글자로."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str).encode("utf-8")


def _error(code: int, error: Exception, message: str) -> JSON:
    body: dict[str, Any] = {"error": message}
    for key in ("log_file", "log_url"):                     # IR 생성 실패 — 로그 위치를 같이
        if getattr(error, key, None) is not None:
            body[key] = getattr(error, key)
    return JSON(body, status_code=code)


def create_app(root: Path, llm=None) -> FastAPI:
    """llm: 테스트에서 가짜 LLM 을 끼울 때. 없으면 .env 의 OpenAI."""
    root = Path(root)
    app = FastAPI(title="테스트 데이터 생성기", default_response_class=JSON,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.root = root
    app.state.llm = llm
    app.state.pending = services.Pending()

    @app.exception_handler(ValueError)
    def _value_error(request: Request, error: ValueError) -> JSON:
        from tap.ir.input_review import ReviewConflict
        return _error(409 if isinstance(error, ReviewConflict) else 400, error, str(error))

    @app.exception_handler(Exception)
    def _server_error(request: Request, error: Exception) -> JSON:
        return _error(500, error, f"{type(error).__name__}: {error}")

    @app.middleware("http")
    async def _no_cache(request: Request, call_next):
        """화면 파일을 브라우저가 옛것으로 쓰지 않게 — 매번 서버에 바뀌었는지 묻는다 (캐시 지정이 없는 응답만)."""
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

    for r in (register.router, inspect.router, run.router, history.router, admin.router, common.router):
        app.include_router(r)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
    def _unknown(rest: str) -> JSON:
        return JSON({"error": "없는 경로"}, status_code=404)

    @app.get("/tap-data.js", include_in_schema=False)
    def tap_data() -> Response:
        """지금 화면용 화면 데이터 — 요청마다 새로 만든다. React 로 다 옮기면 지운다 (JSON 은 /api/common/data)."""
        raw = "window.TAP_DATA = " + json.dumps(ui_data(root), ensure_ascii=False) + ";\n"
        return Response(raw, media_type="application/javascript; charset=utf-8", headers={"Cache-Control": "no-store"})

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(root / "web/offline-ui.html")

    app.mount("/", StaticFiles(directory=root / "web", check_dir=False), name="web")   # 화면 폴더가 없어도 API 는 뜬다 (테스트 · 예전과 같다)
    return app
