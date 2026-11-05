"""트레이스 · 예산 — 요청 하나를 처리하는 동안 LLM 호출마다 단계 · 토큰 · 지연 · 비용을 남기고, 예산을 넘으면 멈춘다.

- 예산(요청당): LLM 호출 수 · 토큰 · 시간 · 비용 상한. 호출하기 전에 확인하고, 넘으면 BudgetExceeded 로 멈춘다
  (이미 받은 결과는 버리지 않는다 — 다음 호출을 막는다).
- 재시도: 형식 실패 · 거부 · 일시적 API 오류만 정해진 횟수까지. 받은 뒤 검사(근거 구절 · 상태 소속)에서 걸린 것은
  다시 물어도 같은 판단이 나올 수 있어 재시도하지 않고 이유와 함께 거절한다. 재시도도 호출 수 · 토큰에 포함된다.
- 단계 시간(span): ① 의도 분석 · ② 경로 탐색 · ③ API 선택 각각의 전체 시간 (LLM 호출 + 코드).
설정은 data/config/llm.yaml (budget · pricing). 가격이 비어 있으면 비용은 계산하지 않고 토큰만 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import yaml

# 응답 스키마 이름 → 단계 (LLM 함수는 (messages, schema) 만 받으므로 스키마로 단계를 안다)
STAGE = {"TaskPlanOut": "① 의도 분석", "PathChoiceOut": "② 상태 고르기", "PicksOut": "③ API 고르기",
         "GoalOut": "목표 추출(예전)", "GraphChoice": "그래프 고르기(예전)", "GraphOut": "그래프 재료 추출"}


class Stopped(ValueError):
    """정지조건으로 멈춤 — code 는 혜정 IR 생성과 같은 체계 (RUN_LLM_LIMIT · RUN_TOKEN_LIMIT · LLM_REFUSAL …)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{message} [{code}]")
        self.code = code


class BudgetExceeded(Stopped):
    pass


@dataclass
class Budget:
    max_llm_calls: int = 6
    max_tokens: int = 60000
    max_seconds: float = 180.0
    max_cost_usd: float | None = None
    retries: int = 1                    # 중지조건 · 재시도 OFF 면 0 (analyze_select stop_retry)
    max_output_tokens: int = 4096       # 호출당 출력 토큰 — 혜정 IR 생성과 같은 값


def load_llm_config(path: str | Path | None) -> tuple[Budget, dict[str, dict[str, float]]]:
    """예산 · 가격. 생성 설정 검사 — 상한은 양수, 재시도는 0 이상 정수 (틀리면 ValueError)."""
    p = Path(path) if path else None
    raw = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p and p.exists() else {}
    b = raw.get("budget") or {}
    budget = Budget(**{k: v for k, v in b.items() if k in Budget.__dataclass_fields__ and v is not None})
    if "max_cost_usd" in b:
        budget.max_cost_usd = b["max_cost_usd"]
    for k in ("max_llm_calls", "max_tokens", "max_seconds", "max_output_tokens"):
        v = getattr(budget, k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise ValueError(f"llm.yaml budget.{k} 는 양수여야 합니다: {v!r}")
    if isinstance(budget.retries, bool) or not isinstance(budget.retries, int) or budget.retries < 0:
        raise ValueError(f"llm.yaml budget.retries 는 0 이상 정수여야 합니다: {budget.retries!r}")
    if budget.max_cost_usd is not None and (isinstance(budget.max_cost_usd, bool) or not isinstance(budget.max_cost_usd, (int, float)) or budget.max_cost_usd <= 0):
        raise ValueError(f"llm.yaml budget.max_cost_usd 는 양수여야 합니다: {budget.max_cost_usd!r}")
    return budget, raw.get("pricing") or {}


def retry_wait(e: Exception, attempt: int) -> float | None:
    """다시 물을지 · 얼마나 기다릴지 (초). None 이면 재시도하지 않는다.

    통신 오류는 혜정 IR 생성과 같은 규칙(tap.agent.llm_retry.retry_delay): 타임아웃 · 연결 실패 · 408 · 429 · 500 · 502 · 503 · 504,
    할당량 · 결제 한도 오류는 재시도하지 않음, 지수 대기 + retry-after. 형식 실패(스키마)는 바로 다시 묻는다.
    LLM 거절 · 출력 토큰 한도 · 예산 같은 정지조건(Stopped)은 다시 묻지 않는다.
    """
    from pydantic import ValidationError

    from tap.goal.extract import GoalError
    if isinstance(e, Stopped):
        return None
    if isinstance(e, (GoalError, ValidationError)):
        return 0.0
    from tap.agent.config import CONFIG
    from tap.agent.llm_retry import retry_delay
    return retry_delay(e, CONFIG, attempt)


class Trace:
    def __init__(self, request: str, budget: Budget | None = None, pricing: dict[str, dict[str, float]] | None = None):
        self.request = request
        self.budget = budget or Budget()
        self.pricing = pricing or {}
        self.calls: list[dict[str, Any]] = []
        self.spans: list[dict[str, Any]] = []
        self.status = "진행 중"
        self.started = datetime.now().astimezone().isoformat(timespec="seconds")
        self._t0 = time.perf_counter()
        self.total_ms: int | None = None
        self.options: dict[str, Any] = {}

    # ── 예산 ──
    def totals(self) -> dict[str, Any]:
        tok_in = sum(c["input_tokens"] or 0 for c in self.calls)
        tok_out = sum(c["output_tokens"] or 0 for c in self.calls)
        costs = [c["cost_usd"] for c in self.calls]
        return {"llm_calls": len(self.calls), "input_tokens": tok_in, "output_tokens": tok_out, "tokens": tok_in + tok_out,
                "cost_usd": round(sum(costs), 6) if costs and None not in costs else None,
                "llm_ms": sum(c["ms"] for c in self.calls),
                "ms": self.total_ms if self.total_ms is not None else int((time.perf_counter() - self._t0) * 1000)}

    def _check(self, stage: str) -> None:
        t, b = self.totals(), self.budget
        why = code = None
        if t["llm_calls"] >= b.max_llm_calls:
            why, code = f"LLM 호출 {t['llm_calls']}회 — 상한 {b.max_llm_calls}회", "RUN_LLM_LIMIT"
        elif t["tokens"] >= b.max_tokens:
            why, code = f"토큰 {t['tokens']} — 상한 {b.max_tokens}", "RUN_TOKEN_LIMIT"
        elif t["ms"] / 1000 >= b.max_seconds:
            why, code = f"{t['ms'] / 1000:.1f}초 — 상한 {b.max_seconds}초", "RUN_TIME_LIMIT"
        elif b.max_cost_usd is not None and t["cost_usd"] is not None and t["cost_usd"] >= b.max_cost_usd:
            why, code = f"비용 ${t['cost_usd']:.4f} — 상한 ${b.max_cost_usd}", "RUN_COST_LIMIT"
        if why:
            self.status = f"중단: 예산 초과 ({stage} 전, {why}) [{code}]"
            raise BudgetExceeded(code, f"중단: 예산 초과 ({stage} 전, {why})")

    def _cost(self, model: str | None, tin: int | None, tout: int | None, cached: int | None) -> float | None:
        p = self.pricing.get(model or "") if model else None
        if not p or tin is None or tout is None or p.get("input") is None or p.get("output") is None:
            return None
        cached = cached or 0
        cin = p.get("cached_input", p["input"])
        return round(((tin - cached) * p["input"] + cached * cin + tout * p["output"]) / 1_000_000, 6)

    # ── LLM 감싸기 ──
    def wrap(self, llm):
        """LLM 함수를 감싸 호출마다 기록 · 예산 확인 · 재시도. 토큰은 llm.last_usage 가 있으면 (openai_parse 가 채운다)."""
        def call(messages, schema):
            stage = STAGE.get(schema.__name__, schema.__name__)
            for attempt in range(1, self.budget.retries + 2):
                self._check(stage)
                try:
                    llm.last_usage = None
                except AttributeError:          # pragma: no cover
                    pass
                t = time.perf_counter()
                rec: dict[str, Any] = {"stage": stage, "attempt": attempt, "status": "ok"}
                try:
                    return llm(messages, schema)
                except Exception as e:
                    rec["status"] = f"실패: {type(e).__name__}: {str(e)[:160]}"
                    wait = retry_wait(e, attempt - 1)
                    if attempt > self.budget.retries or wait is None:
                        if isinstance(e, Stopped):
                            self.status = f"중단: {e}"
                        raise
                    left = self.budget.max_seconds - (time.perf_counter() - self._t0)
                    if wait >= left:            # 기다리는 동안 시간 예산이 끝난다 — 기다리지 않고 멈춘다
                        self.status = f"중단: 재시도 대기 {wait:.1f}초가 남은 시간 {max(left, 0):.1f}초보다 김 [RETRY_WAIT_BUDGET]"
                        raise Stopped("RETRY_WAIT_BUDGET", f"재시도 대기 {wait:.1f}초가 남은 시간보다 김") from e
                    rec["retry_wait_s"] = round(wait, 2)
                    if wait:
                        time.sleep(wait)
                finally:
                    u = getattr(llm, "last_usage", None) or {}
                    rec.update(ms=int((time.perf_counter() - t) * 1000), model=u.get("model"),
                               input_tokens=u.get("input"), output_tokens=u.get("output"), cached_tokens=u.get("cached"),
                               prompt_chars=sum(len(m["content"]) for m in messages))
                    rec["cost_usd"] = self._cost(rec["model"], rec["input_tokens"], rec["output_tokens"], rec["cached_tokens"])
                    self.calls.append(rec)
        return call

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        n = len(self.calls)
        try:
            yield
        finally:
            self.spans.append({"name": name, "ms": int((time.perf_counter() - t) * 1000), "llm_calls": len(self.calls) - n})

    # ── 기록 ──
    def finish(self, status: str | None = None) -> None:
        if status:
            self.status = status
        self.total_ms = int((time.perf_counter() - self._t0) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {"request": self.request, "started": self.started, "status": self.status, "options": self.options, "budget": asdict(self.budget),
                "totals": self.totals(), "spans": self.spans, "calls": self.calls}

    def save(self, directory: str | Path) -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-") + hashlib.sha1(self.request.encode("utf-8")).hexdigest()[:6]
        p = d / f"{name}.json"
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def summary(self) -> str:
        t = self.totals()
        lines = [f"[트레이스] {self.status} · 전체 {t['ms']}ms · LLM {t['llm_calls']}회 {t['llm_ms']}ms · "
                 f"토큰 {t['input_tokens']}+{t['output_tokens']} · 비용 " + (f"${t['cost_usd']:.4f}" if t["cost_usd"] is not None else "가격 미설정")]
        lines += [f"  단계 {s['name']}: {s['ms']}ms (LLM {s['llm_calls']}회)" for s in self.spans]
        lines += [f"  호출 {c['stage']} #{c['attempt']} {c['status']} · {c['ms']}ms · 토큰 {c['input_tokens']}+{c['output_tokens']}"
                  + (f" · ${c['cost_usd']:.4f}" if c["cost_usd"] is not None else "") for c in self.calls]
        return "\n".join(lines)
