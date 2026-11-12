"""테스트용 서버 — FastAPI 앱을 실제 포트로 띄운다 (docs/fastapi.md 6.2).

예전 테스트가 쓰던 ThreadingHTTPServer 와 같은 모양(server_port · server_address · serve_forever · shutdown · server_close)이라,
테스트 본문은 HTTP 로 호출하는 그대로 둔다. 앱과 테스트가 한 프로세스라 monkeypatch 로 바꿔 끼운 함수도 그대로 먹는다.
"""
from __future__ import annotations

import socket
import threading
import time

import uvicorn


class AppServer:
    def __init__(self, app) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.server_address = self._sock.getsockname()
        self.server_port = self.server_address[1]
        self._server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        self._thread = threading.Thread(target=self._server.run, kwargs={"sockets": [self._sock]}, daemon=True)
        self._thread.start()
        for _ in range(500):                                # 뜰 때까지 (최대 5초)
            if self._server.started:
                break
            time.sleep(0.01)

    def serve_forever(self) -> None:                        # 이미 돌고 있다 — 예전 테스트의 Thread(target=serve_forever) 호환
        return None

    def shutdown(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def server_close(self) -> None:
        self._sock.close()
