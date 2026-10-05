# streamlit run day05/mini_project_1/streamlit/streamlit_chat.py
import streamlit as st
from time import perf_counter

from adaptive_rag import build_adaptive_graph, prepare_resources
from chat_service import resolve_question, stream_reply
from prepare_index import ensure_indexes
from rag_config import load_settings
from run_history import RunRecorder, render_history
from source_downloads import render_source_downloads


# 모델과 검색기 및 그래프를 준비해 재사용하도록 캐싱한다.
@st.cache_resource(show_spinner=False)
def get_resources(settings):
    resources = prepare_resources(settings)
    resources["graph"] = build_adaptive_graph(resources, settings)
    return resources


st.session_state.setdefault("messages", [])
st.session_state.setdefault("run_history", [])
st.session_state.setdefault("screen", "chat")
st.set_page_config(layout="wide" if st.session_state.screen == "history" else "centered")

with st.sidebar:
    st.header("상태")
    st.metric("메시지 수", len(st.session_state.messages))
    if st.button("이력 확인" if st.session_state.screen == "chat" else "챗봇으로 돌아가기"):
        st.session_state.screen = "history" if st.session_state.screen == "chat" else "chat"
        st.rerun()
    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("Adaptive RAG로 문서 근거에 따른 답변을 생성합니다.")

if st.session_state.screen == "history":
    render_history(st.session_state.run_history)
    st.stop()

st.title("Hmall 협력사 매뉴얼 챗봇")

with st.expander("어떤 챗봇인가요?"):
    st.markdown(
        """
현대홈쇼핑 협력사를 위한 매뉴얼에 답변하는 챗봇입니다.

대상 매뉴얼 목록

1. 협력사 운영 통합 안내서
2. Hmall 소개서
3. 쇼라 소개서
4. 광고 상품 소개서
5. 협력사시스템 사용법
6. 신규 협력사 입점 절차 안내
7. 데이터 영역 광고 제안서
8. QA가이드
"""
    )

if "messages" not in st.session_state:
    st.session_state.messages = []

startup_error = None
startup_start = perf_counter()
startup_steps = []
try:
    settings = load_settings()
    settings_end = perf_counter()
    startup_steps.append({"단계": "설정 로딩", "시작(초)": 0.0,
                          "소요(초)": settings_end - startup_start, "상태": "완료"})
    ensure_indexes(settings)
    indexes_end = perf_counter()
    startup_steps.append({"단계": "저장소 확인", "시작(초)": settings_end - startup_start,
                          "소요(초)": indexes_end - settings_end, "상태": "완료"})
    resources = get_resources(settings)
    startup_steps.append({"단계": "자원 캐시 조회·준비", "시작(초)": indexes_end - startup_start,
                          "소요(초)": perf_counter() - indexes_end, "상태": "완료"})
except ValueError as exc:
    startup_error = str(exc)
except Exception:
    startup_error = "서비스를 준비하지 못했습니다. 환경 설정과 인덱스를 확인한 뒤 앱을 재시작하세요."

for message_index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            render_source_downloads(message.get("sources", []), f"chat_{message_index}")

if startup_error:
    with st.chat_message("assistant"):
        st.markdown(startup_error)

if prompt := st.chat_input("메시지를 입력하세요", disabled=bool(startup_error)):
    # 현재 입력을 추가하기 전 이력: 현재 질문이 중복 전달되지 않는다.
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    result = {}
    recorder = RunRecorder(settings)
    recorder.started = startup_start
    recorder.steps.extend(startup_steps)
    with st.chat_message("assistant"):
        try:
            with recorder.bind():
                resolution = resolve_question(prompt, history, resources["resolver"], settings)
                st.write_stream(stream_reply(prompt, resolution, resources, result))
        except Exception as exc:
            text = "응답을 완료하지 못했습니다. 질문의 대상을 명시해 다시 입력해주세요."
            st.markdown(text)
            result.update(content=text, sources=[], status="error", original_question=prompt,
                          error_type=type(exc).__name__)
        render_source_downloads(result.get("sources", []), f"chat_{len(st.session_state.messages)}")
    result["telemetry"] = recorder.snapshot()
    st.session_state.run_history.append(dict(result))
    st.session_state.messages.append({"role": "assistant", **result})
