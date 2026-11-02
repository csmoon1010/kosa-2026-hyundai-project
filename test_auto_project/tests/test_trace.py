"""트레이스 · 예산 — 호출별 단계 · 토큰 · 지연 · 비용, 재시도, 예산 초과 시 멈춤 (LLM 없이)."""
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from tap.goal.extract import GoalError
from tap.trace import Budget, BudgetExceeded, Trace, load_llm_config

ROOT = Path(__file__).resolve().parents[1]
PRICE = {"m": {"input": 2.0, "cached_input": 0.5, "output": 10.0}}


class TaskPlanOut(BaseModel):                       # 스키마 이름으로 단계를 안다
    x: int = 1


class PathChoiceOut(BaseModel):
    x: int = 1


def fake(results, usage=(1000, 200, 0)):
    """results 를 차례로 돌려주는 가짜 LLM — Exception 이면 던진다. openai_parse 처럼 last_usage 를 채운다."""
    it = iter(results)

    def llm(messages, schema):
        llm.last_usage = {"model": "m", "input": usage[0], "output": usage[1], "cached": usage[2]}
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return schema()
    return llm


MSG = [{"role": "system", "content": "가" * 100}]


def test_records_stage_tokens_cost_and_spans():
    t = Trace("요청", Budget(), PRICE)
    llm = t.wrap(fake(["ok", "ok"], usage=(1000, 200, 400)))
    with t.span("① 의도 분석"):
        llm(MSG, TaskPlanOut)
    with t.span("② 경로 탐색"):
        llm(MSG, PathChoiceOut)
    a, b = t.calls
    assert (a["stage"], b["stage"], a["attempt"], a["status"]) == ("① 의도 분석", "② 상태 고르기", 1, "ok")
    assert (a["input_tokens"], a["output_tokens"], a["cached_tokens"], a["prompt_chars"]) == (1000, 200, 400, 100)
    assert a["cost_usd"] == round((600 * 2 + 400 * 0.5 + 200 * 10) / 1e6, 6)
    tot = t.totals()
    assert (tot["llm_calls"], tot["tokens"], tot["cost_usd"]) == (2, 2400, round(2 * a["cost_usd"], 6))
    assert [s["name"] for s in t.spans] == ["① 의도 분석", "② 경로 탐색"] and t.spans[0]["llm_calls"] == 1


def test_no_price_means_no_cost():
    t = Trace("요청", Budget(), {})
    t.wrap(fake(["ok"]))(MSG, TaskPlanOut)
    assert t.calls[0]["cost_usd"] is None and t.totals()["cost_usd"] is None and "가격 미설정" in t.summary()


def test_retries_format_failure_once():
    t = Trace("요청", Budget(retries=1), PRICE)
    out = t.wrap(fake([GoalError("형식을 지키지 못함"), "ok"]))(MSG, TaskPlanOut)
    assert isinstance(out, TaskPlanOut) and [c["attempt"] for c in t.calls] == [1, 2]
    assert t.calls[0]["status"].startswith("실패: GoalError") and t.totals()["tokens"] == 2400   # 재시도도 토큰에 잡힌다
    t2 = Trace("요청", Budget(retries=1), PRICE)
    with pytest.raises(GoalError):
        t2.wrap(fake([GoalError("x"), GoalError("y")]))(MSG, TaskPlanOut)
    assert len(t2.calls) == 2
    t3 = Trace("요청", Budget(retries=1), PRICE)
    with pytest.raises(KeyError):                                                        # 다시 물어도 소용없는 오류는 바로 멈춤
        t3.wrap(fake([KeyError("bug")]))(MSG, TaskPlanOut)
    assert len(t3.calls) == 1


@pytest.mark.parametrize("budget, msg", [
    (Budget(max_llm_calls=1), "LLM 호출 1회 — 상한 1회"),
    (Budget(max_tokens=1000), "토큰 1200 — 상한 1000"),
    (Budget(max_cost_usd=0.001), "비용"),
])
def test_budget_stops_before_next_call(budget, msg):
    t = Trace("요청", budget, PRICE)
    llm = t.wrap(fake(["ok", "ok"]))
    llm(MSG, TaskPlanOut)                                                                # 첫 호출 결과는 그대로
    with pytest.raises(BudgetExceeded, match=msg):
        llm(MSG, PathChoiceOut)
    assert len(t.calls) == 1 and t.status.startswith("중단: 예산 초과 (② 상태 고르기 전")


def test_save_and_config(tmp_path):
    t = Trace("배송완료 취소", Budget(), PRICE)
    t.wrap(fake(["ok"]))(MSG, TaskPlanOut)
    t.finish("완료")
    d = json.loads(t.save(tmp_path).read_text(encoding="utf-8"))
    assert d["status"] == "완료" and d["totals"]["llm_calls"] == 1 and d["calls"][0]["stage"] == "① 의도 분석"
    budget, pricing = load_llm_config(ROOT / "data/config/llm.yaml")
    assert budget.max_llm_calls == 6 and budget.retries == 1 and "input" in pricing["gpt-5.4"]
    assert load_llm_config(tmp_path / "없음.yaml")[0] == Budget()


def test_analyze_select_saves_trace_even_when_stopped(tmp_path):
    from tap.cli import analyze_select
    q = "배송완료된 주문 하나를 배송완료 취소해줘"

    def llm(messages, schema):
        return schema.model_validate({"original_question": q, "tasks": [], "unresolved": []})
    from tap.trace import Budget as B
    t = Trace(q, B(max_llm_calls=0), {})
    with pytest.raises(BudgetExceeded):
        analyze_select(q, llm=llm, trace=t, trace_dir=tmp_path)
    saved = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert saved["status"].startswith("중단: 예산 초과 (① 의도 분석 전")
    r = analyze_select(q, llm=llm, trace_dir=tmp_path)                                  # 업무 없음 → LLM 1번(의도 분석)
    assert r["trace"].totals()["llm_calls"] == 1 and [s["name"] for s in r["trace"].spans] == ["① 의도 분석", "② 경로 탐색", "③ API 선택"]
