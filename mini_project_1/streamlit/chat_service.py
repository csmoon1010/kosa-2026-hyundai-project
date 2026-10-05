"""세션 이력으로 질문을 보완하고 최종 답변 토큰을 전달한다."""
import json
import re

import tiktoken

from adaptive_rag import ResolvedQuestion, ROUTE_LABELS
from run_history import CURRENT_RUN, timed
from time import perf_counter


# 제한된 대화 이력으로 후속 질문을 보완하거나 확인 질문을 만든다.
@timed("질문 보완·이력 준비")
def resolve_question(question, messages, resolver, settings):
    question = question.strip()
    if not question:
        raise ValueError("질문을 입력하세요.")
    # 현재 입력을 append하기 전 이력을 전달받는다. 오류·미완료 턴은 제외한다.
    turns, user = [], None
    for message in messages:
        if message["role"] == "user":
            user = message["content"]
        elif message["role"] == "assistant" and user is not None:
            if message.get("status", "complete") in ("complete", "clarification"):
                turns.append([{"role": "user", "content": user},
                              {"role": "assistant", "content": message["content"]}])
            user = None
    encoding = tiktoken.get_encoding("o200k_base")
    selected = []
    limit = settings["history_max_tokens"]
    for turn in reversed(turns[-settings["history_max_turns"]:]):
        candidate = turn + selected
        text = json.dumps(candidate, ensure_ascii=False)
        if len(encoding.encode(text, disallowed_special=())) <= limit:
            selected = candidate
            continue
        if not selected:
            # 가장 최근 사용자 질문을 우선 보존하고 긴 답변을 제한한다.
            short_turn = [dict(turn[0]), dict(turn[1])]
            for index in (1, 0):
                tokens = encoding.encode(short_turn[index]["content"], disallowed_special=())
                lo, hi = 0, len(tokens)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    short_turn[index]["content"] = encoding.decode(tokens[:mid])
                    serialized = json.dumps(short_turn, ensure_ascii=False)
                    if len(encoding.encode(serialized, disallowed_special=())) <= limit:
                        lo = mid
                    else:
                        hi = mid - 1
                short_turn[index]["content"] = encoding.decode(tokens[:lo])
                if len(encoding.encode(json.dumps(short_turn, ensure_ascii=False), disallowed_special=())) <= limit:
                    break
            selected = short_turn
        break
    history = json.dumps(selected, ensure_ascii=False) if selected else ""
    if not history:
        result = ResolvedQuestion(resolved_question=question, needs_clarification=False,
                                  clarification_question="")
    else:
        recorder = CURRENT_RUN.get()
        raw = resolver.invoke({"question": question, "history": history},
                              config={"callbacks": [recorder], "metadata": {"history_stage": "질문 보완"}} if recorder else None)
        result = raw if isinstance(raw, ResolvedQuestion) else ResolvedQuestion.model_validate(raw)
    if result.needs_clarification and not result.clarification_question.strip():
        raise ValueError("확인 질문을 생성하지 못했습니다. 대상을 명시해 다시 질문하세요.")
    if not result.needs_clarification and not result.resolved_question.strip():
        raise ValueError("검색 질문을 생성하지 못했습니다. 다시 질문하세요.")
    return {**result.model_dump(), "history": history}


# 답변 토큰을 전달하고 완료된 답변과 출처를 요청 결과에 저장한다.
def stream_reply(question, resolution, resources, request_result):
    request_result.update(status="pending", content="", sources=[], original_question=question,
                          resolved_question=resolution["resolved_question"])
    if resolution["needs_clarification"]:
        text = resolution["clarification_question"].strip()
        yield text
        request_result.update(content=text, status="clarification")
        return
    state = {"question": resolution["resolved_question"].strip(), "original_question": question,
             "history": resolution["history"], "route_type": "기본", "confidence": 0.0,
             "classification_reason": "", "selected_route": "base_search", "fallback": False,
             "fallback_reason": "", "docs": [], "answer": ""}
    emitted = []
    pending = ""
    displayed = []
    generated = False
    recorder = CURRENT_RUN.get()
    try:
        # 같은 실행의 토큰·최종 상태를 받되 답변 노드의 토큰만 표시한다.
        stream_options = {"stream_mode": ["messages", "updates"]}
        if recorder:
            stream_options["config"] = {"callbacks": [recorder]}
        for mode, payload in resources["graph"].stream(state, **stream_options):
            if mode == "messages":
                chunk, metadata = payload
                if metadata.get("langgraph_node") != "generate_answer":
                    continue
                content = chunk.content
                if isinstance(content, str):
                    text = content
                else:
                    text = "".join(block.get("text", "") for block in content
                                   if isinstance(block, dict) and block.get("type") == "text")
                if text:
                    emitted.append(text)
                    # 번호가 여러 토큰으로 나뉘어도 화면에 잠깐 노출하지 않는다.
                    pending += text
                    pending = re.sub(r"\[\d+\]", "", pending)
                    partial = re.search(r"\[\d*$", pending)
                    end = partial.start() if partial else len(pending)
                    visible, pending = pending[:end], pending[end:]
                    if visible:
                        if recorder and recorder.first_token_seconds is None:
                            recorder.first_token_seconds = perf_counter() - recorder.started
                        displayed.append(visible)
                        yield visible
            elif mode == "updates":
                for node, update in payload.items():
                    if isinstance(update, dict):
                        state.update(update)
                        request_result["contexts"] = [{"번호": i, "파일": doc.metadata.get("source"),
                            "페이지": doc.metadata.get("page"), "본문": doc.page_content}
                            for i, doc in enumerate(state["docs"], 1)]
                        request_result["trace"] = {key: state[key] for key in ("route_type", "confidence",
                            "classification_reason", "selected_route", "fallback", "fallback_reason")}
                        if node == "generate_answer":
                            generated = True
        answer = state["answer"]
        if not generated or not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("답변 스트림이 정상 완료되지 않았습니다.")
        if not emitted or "".join(emitted) != answer:
            # 완성 답변을 다시 호출하거나 가짜 스트리밍으로 대체하지 않는다.
            raise RuntimeError("답변 토큰 스트림과 최종 답변이 일치하지 않습니다.")
        if pending:
            displayed.append(pending)
            yield pending
        # 실제 답변에서 인용한 문서만 출처로 사용한다.
        cited = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
        sources = [{"context_number": i, "source": doc.metadata.get("source"),
                    "page": doc.metadata.get("page")} for i, doc in enumerate(state["docs"], 1)
                   if i in cited]
        for context in request_result.get("contexts", []):
            context["답변에 인용"] = context["번호"] in cited
        references = []
        seen = set()
        for source in sources:
            key = (source["source"], source["page"])
            if key in seen:
                continue
            seen.add(key)
            filename = source["source"] or "파일명 미상"
            page = f'{source["page"]}페이지' if source["page"] is not None else "페이지 정보 없음"
            references.append(f"- {filename} — {page}")
        if references:
            footer = "\n\n**&lt;출처&gt;**\n\n" + "\n".join(references)
            displayed.append(footer)
            yield footer
        trace = {key: state[key] for key in ("route_type", "confidence", "classification_reason",
                 "selected_route", "fallback", "fallback_reason")}
        request_result.update(content="".join(displayed), sources=sources, trace=trace,
                              search_method=ROUTE_LABELS[state["selected_route"]], status="complete")
    except Exception:
        request_result.update(status="error", content="", sources=[])
        raise
