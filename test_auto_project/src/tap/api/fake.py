"""가짜 LLM — 화면 끝까지 테스트(Playwright)와 화면 개발용. 운영에서 쓰지 않는다 (docs/react.md 8.3 · 결정 4).

    .venv/bin/python -m tap.cli serve --fake-llm --temp-data --port 8799

- 분석(①②③): 어떤 요청이든 '배송완료된 주문을 배송완료 취소'(주문상태 배송완료 → 출고) 업무 하나로 답한다.
  근거 구절은 요청 원문 그대로라 코드 검사(원문에 있는가)를 통과한다. ③ 에서 LLM 에 묻는 단계가 있으면 늘 첫 후보(A).
- IR 생성: 단계마다 API 요청 필드를 모두 '확인 필요(unresolved)' 로 둔다 — 실제 값은 고르지 않는다.
- 비용 · 네트워크 없음. 서버 상태 확인(/api/common/health)에 fake_llm: true 가 붙어 화면이 '가짜 LLM' 을 표시한다.
"""
from __future__ import annotations

import typing
from typing import Any

from pydantic import BaseModel


def _utterance(messages: list[dict[str, str]]) -> str:
    return next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")


def _literals(model: type[BaseModel], field: str) -> tuple[Any, ...]:
    """create_model 로 만든 스키마의 Literal 칸 값 (단계 key · 후보 기호)."""
    return typing.get_args(model.model_fields[field].annotation)


def fake_llm(messages: list[dict[str, str]], schema: type[BaseModel]) -> BaseModel:
    name = schema.__name__
    if name == "TaskPlanOut":                                       # ① 업무
        utt = _utterance(messages)
        return schema.model_validate({"original_question": utt, "unresolved": [], "injections": [], "tasks": [
            {"sequence": 1, "domain": "OD", "origin": "기존", "action": "배송완료취소", "conditions": "배송완료된 주문",
             "constraints": [], "depends_on": [], "count": 1, "source_phrases": [utt]}]})
    if name == "PicksOut":                                          # ③ 애매한 단계 — 늘 첫 후보
        pick = typing.get_args(schema.model_fields["picks"].annotation)[0]
        return schema.model_validate({"picks": [{"key": k, "choice": "A", "reason": "가짜 LLM — 첫 후보", "concerns": []}
                                                for k in _literals(pick, "key")]})
    if name == "PathChoiceOut":                                     # ② 업무마다 그래프 · 상태
        return schema.model_validate({"unresolved": [], "choices": [
            {"sequence": 1, "graph_id": "ORD_STAT_GBCD", "from_state": "배송완료", "to_state": "출고", "must_pass": [],
             "state_phrases": [], "reason": "가짜 LLM"}]})
    raise ValueError(f"가짜 LLM 이 모르는 질문입니다: {name}")


class FakeRuntime:
    """IR 생성 런타임 대신 — tap.agent.runtime.Runtime 과 같은 자리 (run · usage · trace · set_options)."""

    def __init__(self, tools, config):
        self.tools = tools
        self.usage = dict(llm_calls=0, input_tokens=0, output_tokens=0, total_tokens=0, elapsed_seconds=0)
        self.trace: list[dict[str, Any]] = []
        self.on_event = None
        self.budget = None
        self.sessions: dict[str, dict[str, int]] = {}
        self.errors = {"final_backend": "가짜 LLM — 최종 검증 실패", "final_check": "가짜 LLM — 최종 검증 오류"}

    def emit(self, event: str, current: dict[str, Any], turn: int, **fields: Any) -> None:
        """최종 IR 검증 결과 등 진행 이벤트 — 실제 런타임과 같은 모양으로 화면에 보낸다."""
        if self.on_event:
            self.on_event(dict(event=event, step_id=current["step_id"], turn=turn, **fields))

    def stop(self, current: dict[str, Any], turn: int, verdict: dict[str, Any], message: str) -> None:
        raise ValueError(f"{message}: {verdict.get('errors')}")

    def repair(self, current: dict[str, Any], previous: dict[str, Any], errors: list[dict[str, Any]]) -> dict[str, Any]:
        raise ValueError(f"가짜 LLM 은 고치지 않습니다: {errors}")

    def set_options(self, options: dict[str, Any]) -> None:
        """생성 옵션(재시도 · KB 검색 · 문맥 압축)은 가짜에선 영향 없음."""

    def run(self, current: dict[str, Any], previous: dict[str, Any], *args: Any) -> dict[str, Any]:
        self.usage["llm_calls"] += 1
        self.sessions[current["step_id"]] = {"step_turn": 1}
        inputs = [dict(field=f["name"], parameter_path=f["path"], xml_path=f.get("xmlPath"), type=f["type"],
                       source="unresolved", origin="unresolved", value=None, ref=None, reason="가짜 LLM — 값 확인 필요",
                       evidence=[])
                  for f in self.tools.schema(current["selected_api_id"])["parameters"]]
        return dict(step_id=current["step_id"], inputs=inputs, outputs=[], bindings=[], assertions=[], unresolved=[])
