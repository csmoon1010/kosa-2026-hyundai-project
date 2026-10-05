"""요청별 계측. 공유 검색 자원에는 세션 정보를 저장하지 않는다."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from threading import RLock
from time import perf_counter
from zoneinfo import ZoneInfo

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.embeddings import Embeddings

CURRENT_RUN = ContextVar("chatbot_run", default=None)
# mini_project_final.ipynb 공통 설정·pre_llm_cost와 동일한 방식.
PRICES = {"gpt-5.4-mini": (0.75, 4.50), "text-embedding-3-small": (0.02, 0)}


def token_cost(model, input_tokens, cached_tokens, output_tokens, prices=None):
    prices = prices if prices is not None else PRICES
    matches = [name for name in prices if model == name or model.startswith(name + "-")]
    if not matches:
        return None
    pin, pout = prices[max(matches, key=len)]
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


class RunRecorder(UsageMetadataCallbackHandler):
    run_inline = True

    def __init__(self, settings):
        super().__init__()
        self.model = settings["lower_model"]
        self.prices = {settings["model"]: (2.50, 15.00),
                       settings["lower_model"]: (0.75, 4.50),
                       settings["embedding_model"]: (0.02, 0.0)}
        self.started = perf_counter()
        self.timestamp = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
        self.steps = []
        self.calls = []
        self.active = {}
        self.first_token_seconds = None
        self.lock = RLock()

    @contextmanager
    def bind(self):
        token = CURRENT_RUN.set(self)
        try:
            yield self
        finally:
            CURRENT_RUN.reset(token)

    @contextmanager
    def measure(self, name):
        start = perf_counter()
        status = "완료"
        try:
            yield
        except Exception:
            status = "오류"
            raise
        finally:
            with self.lock:
                self.steps.append({"단계": name, "시작(초)": start - self.started,
                                   "소요(초)": perf_counter() - start, "상태": status})

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        with self.lock:
            meta = metadata or {}
            self.active[run_id] = (perf_counter(), meta.get("ls_model_name", self.model),
                                  meta.get("history_stage", meta.get("langgraph_node", "LLM")))

    def add_usage(self, stage, model, usage, seconds, status="완료"):
        usage = usage or {}
        known = "input_tokens" in usage or "prompt_tokens" in usage
        inp = usage.get("input_tokens", usage.get("prompt_tokens", 0))
        out = usage.get("output_tokens", usage.get("completion_tokens", 0))
        cached = usage.get("input_token_details", {}).get("cache_read",
            usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)) or 0
        with self.lock:
            self.calls.append({"단계": stage, "모델": model, "입력 토큰": inp if known else None,
                "캐시 입력 토큰": cached if known else None, "출력 토큰": out if known else None,
                "총 토큰": inp + out if known else None,
                "추정 비용(USD)": token_cost(model, inp, cached, out, self.prices) if known else None,
                "소요(초)": seconds, "상태": status})

    def on_llm_end(self, response, *, run_id, **kwargs):
        super().on_llm_end(response, run_id=run_id, **kwargs)
        start, model, stage = self.active.pop(run_id, (perf_counter(), self.model, "LLM"))
        output = response.llm_output or {}
        usage = output.get("token_usage")
        if response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
            if message is not None:
                usage = getattr(message, "usage_metadata", None) or usage
                model = message.response_metadata.get("model_name", model)
        self.add_usage(stage, model, usage, perf_counter() - start)

    def on_llm_error(self, error, *, run_id, **kwargs):
        start, model, stage = self.active.pop(run_id, (perf_counter(), self.model, "LLM"))
        self.add_usage(stage, model, None, perf_counter() - start, "오류·사용량 미확인")

    def snapshot(self):
        with self.lock:
            known = all(call["총 토큰"] is not None for call in self.calls)
            costs_known = all(call["추정 비용(USD)"] is not None for call in self.calls)
            return {"timestamp": self.timestamp, "steps": sorted(self.steps, key=lambda s: s["시작(초)"]), "api_calls": list(self.calls),
                "total_seconds": perf_counter() - self.started,
                "first_token_seconds": self.first_token_seconds,
                "total_tokens": sum(c["총 토큰"] for c in self.calls) if known else None,
                "cost_usd": sum(c["추정 비용(USD)"] for c in self.calls) if costs_known else None,
                "prices": dict(self.prices), "model_usage": dict(self.usage_metadata)}


def timed(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            recorder = CURRENT_RUN.get()
            if recorder is None:
                return function(*args, **kwargs)
            with recorder.measure(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


class CountedQueryEmbeddings(Embeddings):
    def __init__(self, delegate):
        self.delegate = delegate

    def embed_query(self, text):
        import tiktoken
        recorder = CURRENT_RUN.get()
        start = perf_counter()
        try:
            vector = self.delegate.embed_query(text)
        except Exception:
            if recorder:
                recorder.add_usage("질문 임베딩", self.delegate.model, None,
                                   perf_counter() - start, "오류·사용량 미확인")
            raise
        if recorder:
            tokens = len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=()))
            recorder.add_usage("질문 임베딩(추정)", self.delegate.model,
                               {"input_tokens": tokens, "output_tokens": 0}, perf_counter() - start)
        return vector

    def embed_documents(self, texts):
        return self.delegate.embed_documents(texts)


def search_route_reason(trace):
    """실제 실행 경로와 분류·복귀 기록으로 선택 사유를 설명한다."""
    if trace.get("fallback"):
        reason = trace.get("fallback_reason") or "특수 검색을 사용할 수 없습니다."
        return f"{reason} → 기본 벡터 검색으로 복귀했습니다."
    policies = {
        "base_search": "기본 질문으로 분류되어 기본 벡터 검색을 선택했습니다.",
        "parent_document_search": "조건 질문으로 분류되어 부모 문맥을 가져오는 Parent Document 검색을 선택했습니다.",
        "llm_rerank_search": "부정/예외 질문으로 분류되어 후보 문서를 LLM으로 재정렬하는 검색을 선택했습니다.",
    }
    reason = policies.get(trace.get("selected_route"), "검색 경로 선택 기록이 없습니다.")
    classification = trace.get("classification_reason")
    return f"{reason} 분류 근거: {classification}" if classification else reason


def render_history(records):
    import streamlit as st
    from source_downloads import render_source_downloads

    st.title("이번 세션 실행 이력")
    st.caption("시간은 초, 비용은 노트북의 PRICES × 입력·출력 토큰 / 1,000,000 방식입니다. LLM은 API 사용량, 임베딩은 cl100k_base 추정 토큰을 사용하며 캐시 할인은 적용하지 않습니다.")
    st.caption("단계 시간에는 하위 API 시간이 포함됩니다. 이번 세션 기록만 표시하며 대화 초기화 후에도 이력은 유지됩니다.")
    if not records:
        st.info("이번 세션에 기록된 실행이 없습니다.")
        return
    rows = []
    for index, record in enumerate(records, 1):
        telemetry = record.get("telemetry", {})
        trace = record.get("trace", {})
        rows.append({"실행": index, "시각": telemetry.get("timestamp"),
            "질문": record.get("original_question"), "답변": record.get("content"),
            "상태": record.get("status"), "분류": trace.get("route_type", "미실행"),
            "확신도": trace.get("confidence"), "검색 경로": record.get("search_method"),
            "컨텍스트 수": len(record.get("contexts", [])), "토큰 수(임베딩 추정 포함)": telemetry.get("total_tokens"),
            "추정 비용(USD)": telemetry.get("cost_usd"),
            "첫 토큰까지(초)": telemetry.get("first_token_seconds"),
            "전체(초)": telemetry.get("total_seconds")})
    cost_column = {"추정 비용(USD)": st.column_config.NumberColumn(format="%.8f")}
    st.caption("표에서 실행 행을 클릭하면 아래에 상세 기록이 표시됩니다.")
    event = st.dataframe(rows, hide_index=True, width="stretch", column_config=cost_column,
                         key="history_runs_grid", on_select="rerun", selection_mode="single-row")
    if not event.selection.rows:
        st.info("상세 내용을 볼 실행 행을 선택하세요.")
        return
    selected = event.selection.rows[0]
    if not 0 <= selected < len(records):
        return
    record = records[selected]
    st.subheader(f"실행 {selected + 1} 상세")
    detail_tabs = st.tabs(["질문·답변 상세", "분류 상세", "컨텍스트", "시간·API 사용량"])
    with detail_tabs[0]:
        st.table([{"항목": "질문", "내용": record.get("original_question", "")},
              {"항목": "검색 질문", "내용": record.get("resolved_question", "")},
              {"항목": "답변", "내용": record.get("content", "")}])
        render_source_downloads(record.get("sources", []), f"history_{selected}")
    trace = record.get("trace", {})
    labels = {"route_type": "분류", "confidence": "확신도", "classification_reason": "분류 이유",
              "selected_route": "검색 경로", "fallback": "기본 검색 복귀", "fallback_reason": "복귀 이유"}
    with detail_tabs[1]:
        if trace:
            details = [{"항목": labels.get(key, key), "값": str(value)} for key, value in trace.items()]
            details.append({"항목": "검색 경로 선택 사유", "값": search_route_reason(trace)})
            st.table(details)
        else:
            st.info("분류가 실행되지 않았습니다.")
    contexts = record.get("contexts", [])
    with detail_tabs[2]:
        if contexts:
            st.dataframe([{key: value for key, value in context.items() if key != "본문"}
                          for context in contexts], hide_index=True, width="stretch")
        else:
            st.info("컨텍스트가 없습니다.")
        for context in contexts:
            with st.expander(f'{context["번호"]}. {context["파일"]} · {context["페이지"]}페이지'):
                st.text(context["본문"])
    telemetry = record.get("telemetry", {})
    with detail_tabs[3]:
        st.subheader("단계별 실행 시간")
        st.dataframe(telemetry.get("steps", []), hide_index=True, width="stretch")
        st.subheader("API별 토큰·비용")
        st.dataframe(telemetry.get("api_calls", []), hide_index=True, width="stretch", column_config=cost_column)
        st.caption(f'적용 단가(입력·출력 USD / 1M 토큰): {telemetry.get("prices", {})}')
        st.caption("첫 토큰 시간은 질문 처리 시작부터 답변 본문이 처음 표시될 때까지입니다. 전체 시간은 출처 표시 완료까지입니다. 실패 요청의 미보고 사용량과 실제 청구액은 여기서 확정할 수 없습니다.")
