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


class BudgetExceeded(ValueError):
    pass


@dataclass
class Budget:
    max_llm_calls: int = 6
    max_tokens: int = 60000
    max_seconds: float = 180.0
    max_cost_usd: float | None = None
    retries: int = 1


def load_llm_config(path: str | Path | None) -> tuple[Budget, dict[str, dict[str, float]]]:
    p = Path(path) if path else None
    raw = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p and p.exists() else {}
    b = raw.get("budget") or {}
    budget = Budget(**{k: v for k, v in b.items() if k in Budget.__dataclass_fields__ and v is not None})
    if "max_cost_usd" in b:
        budget.max_cost_usd = b["max_cost_usd"]
    return budget, raw.get("pricing") or {}


def _retryable(e: Exception) -> bool:
    """형식 실패 · 거부 · 일시적 API 오류만 다시 묻는다."""
    from pydantic import ValidationError

    from tap.goal.extract import GoalError
    if isinstance(e, (GoalError, ValidationError)):
        return True
    try:
        import openai
        return isinstance(e, (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError))
    except ImportError:                         # pragma: no cover
        return False


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
        why = None
        if t["llm_calls"] >= b.max_llm_calls:
            why = f"LLM 호출 {t['llm_calls']}회 — 상한 {b.max_llm_calls}회"
        elif t["tokens"] >= b.max_tokens:
            why = f"토큰 {t['tokens']} — 상한 {b.max_tokens}"
        elif t["ms"] / 1000 >= b.max_seconds:
            why = f"{t['ms'] / 1000:.1f}초 — 상한 {b.max_seconds}초"
        elif b.max_cost_usd is not None and t["cost_usd"] is not None and t["cost_usd"] >= b.max_cost_usd:
            why = f"비용 ${t['cost_usd']:.4f} — 상한 ${b.max_cost_usd}"
        if why:
            self.status = f"중단: 예산 초과 ({stage} 전, {why})"
            raise BudgetExceeded(self.status)

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
                    if attempt > self.budget.retries or not _retryable(e):
                        raise
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
        return {"request": self.request, "started": self.started, "status": self.status, "budget": asdict(self.budget),
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
