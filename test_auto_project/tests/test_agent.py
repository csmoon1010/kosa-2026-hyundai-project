"""②③ 계획 에이전트 — 가짜 LLM 이 정해 둔 도구 호출을 차례로 내고, 루프 · 정지 조건 · 제출 검사를 본다 (OpenAI 안 부름)."""
import json
from pathlib import Path

import pytest

from tap.agent.loop import AgentLimits, AgentStopped, run_agent
from tap.agent.tools import tool_specs
from tap.cli import _graphs, analyze_select
from tap.goal.extract import TaskPlan
from tap.trace import Budget, BudgetExceeded, Trace

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/out"
META = json.loads((OUT / "api_metadata.json").read_text(encoding="utf-8"))
OPS = json.loads((OUT / "api_operations.json").read_text(encoding="utf-8"))
CAT = json.loads((OUT / "api_catalog.json").read_text(encoding="utf-8"))
Q = "배송완료된 주문 3건을 배송완료 취소시켜줘"
PHRASES = ["배송완료된 주문", "배송완료 취소"]


def task(seq=1, origin="기존", domain="OD", phrases=(Q,), constraints=(), action="배송완료취소"):
    return {"sequence": seq, "domain": domain, "origin": origin, "action": action, "conditions": "c",
            "constraints": list(constraints), "depends_on": [], "count": 3, "source_phrases": list(phrases)}


def tp_of(q=Q, tasks=None):
    return TaskPlan.model_validate({"original_question": q, "tasks": tasks if tasks is not None else [task()], "unresolved": []})


ROUTE = {"sequence": 1, "graph_id": "ORD_STAT_GBCD", "from_state": "배송완료", "to_state": "출고", "must_pass": [],
         "state_phrases": PHRASES}
PATH = {**ROUTE, "route": 0, "reason": "배송완료 주문을 배송완료취소로 출고로"}
LOOKUP = {"sequence": 1, "step": 0, "api": "selectOshpDtlList", "selector": [{"field": "prgrGb", "value": "P3"}], "reason": "r", "concerns": []}
BACK = {"sequence": 1, "step": 1, "api": "multiOshpBackProcess", "selector": [{"field": "procGb", "value": "PB3"}], "reason": "r", "concerns": []}


def scripted(*turns):
    """턴마다 [(도구 이름, 인자)] — 그대로 tool_calls 로 낸다. 받은 메시지는 calls.seen 에 남긴다."""
    it = iter(turns)
    seen = []

    def llm(messages, tools):
        seen.append([m for m in messages if m["role"] == "tool"])
        calls = [{"id": f"c{len(seen)}-{i}", "name": n, "arguments": json.dumps(a, ensure_ascii=False)}
                 for i, (n, a) in enumerate(next(it))]
        return {"message": {"role": "assistant", "content": None,
                            "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                                           for c in calls]}, "tool_calls": calls}
    llm.seen = seen
    return llm


NORMAL = [[("find_state", {"word": "배송완료", "graph_id": None})],
          [("find_route", ROUTE)],
          [("step_candidates", {"sequence": 1, "step": 0, "route": 0}), ("step_candidates", {"sequence": 1, "step": 1, "route": 0})],
          [("submit_plan", {"paths": [PATH], "apis": [LOOKUP, BACK], "unresolved": []})]]


@pytest.fixture(scope="module")
def graphs():
    return _graphs(None, None)


def run(graphs, llm, tp=None, limits=None, trace=None):
    t = trace or Trace(Q, Budget(max_llm_calls=20, max_tokens=10 ** 9))
    return run_agent(tp or tp_of(), graphs, META, OPS, CAT, t.wrap_tools(llm), t, limits), t


def test_normal_plan_follows_rule(graphs):
    r, t = run(graphs, scripted(*NORMAL))
    sel = r["apis"]
    assert sel.status == "완료" and [x.selected_by for x in sel.api_selection_results] == ["규칙", "규칙"]
    assert [x.selected.selector for x in sel.api_selection_results] == [{"prgrGb": "P3"}, {"procGb": "PB3"}]
    assert r["paths"].paths[0].steps[0].edge == "배송완료취소" and r["agent"]["turns"] == 4 and r["agent"]["rejections"] == []
    assert [x["tool"] for x in t.tools] == ["find_state", "find_route", "step_candidates", "step_candidates", "submit_plan"]
    assert all(x["tier"] == "R0" for x in t.tools) and len(t.calls) == 4 and t.calls[2]["tools"] == ["step_candidates"] * 2


def test_rejected_then_fixed(graphs):
    """후보에 나온 적 없는 API · 빠진 단계는 거절 — 이유를 받고 고쳐 다시 낸다."""
    llm = scripted(*NORMAL[:2],
                   [("submit_plan", {"paths": [PATH], "apis": [{**BACK, "api": "multiOshpProcess"}], "unresolved": []})],
                   [("step_candidates", {"sequence": 1, "step": 0, "route": 0}), ("step_candidates", {"sequence": 1, "step": 1, "route": 0})],
                   NORMAL[3])
    r, t = run(graphs, llm)
    errs = r["agent"]["rejections"][0]
    assert any("도구 결과에 나온 적 없는 API" in e for e in errs) and any("1-0" in e and "정하지 않음" in e for e in errs)
    assert "errors" in llm.seen[3][-1]["content"]                                   # 거절 이유가 다음 턴에 LLM 에게 간다
    assert r["apis"].status == "완료" and [x["ok"] for x in t.tools if x["tool"] == "submit_plan"] == [False, True]


def test_choice_against_rule_is_tentative(graphs):
    """규칙 추천과 다르게 고르면 가선택 — 사람이 등록 때 그 단계를 확인한다."""
    other = {**BACK, "selector": [{"field": "procGb", "value": "PB2"}]}
    r, _ = run(graphs, scripted(*NORMAL[:3], [("submit_plan", {"paths": [PATH], "apis": [LOOKUP, other], "unresolved": []})]))
    s = r["apis"].api_selection_results[1]
    assert (s.selection_status, s.selected_by) == ("가선택", "LLM") and "규칙 추천(multiOshpBackProcess {'procGb': 'PB3'})과 다르게" in s.selection_reason
    assert r["apis"].status == "검토 필요"


def test_wrong_state_is_tool_error(graphs):
    """요청의 말에 없는 상태 · 그래프에 없는 상태는 검사가 막는다 — 도구 결과의 error 로 돌려준다."""
    bad = {**ROUTE, "state_phrases": ["없는 구절"]}
    llm = scripted([("find_route", bad)], [("find_route", ROUTE)], *NORMAL[2:])
    r, t = run(graphs, llm)
    assert t.tools[0]["ok"] is False and "원문" in t.tools[0]["result"] and r["apis"].status == "완료"


def test_stop_on_repeats(graphs):
    same = [("get_graph", {"graph_id": "ORD_STAT_GBCD"})]
    with pytest.raises(AgentStopped, match="같은 입력으로 3번 되풀이") as e:
        run(graphs, scripted(same, same, same, same))
    assert e.value.agent["turns"] == 4


def test_stop_on_rejections(graphs):
    bad = [("submit_plan", {"paths": [PATH], "apis": [], "unresolved": []})]
    with pytest.raises(AgentStopped, match="3번 거절"):
        run(graphs, scripted(NORMAL[1], bad, bad, bad))


def test_stop_on_turns_and_tool_calls(graphs):
    turns = [[("find_state", {"word": w, "graph_id": None})] for w in ("가", "나", "다")]
    with pytest.raises(AgentStopped, match="턴 2번 안에"):
        run(graphs, scripted(*turns), limits=AgentLimits(max_turns=2))
    many = [[("find_state", {"word": f"말{i}", "graph_id": None}) for i in range(5)]]
    with pytest.raises(AgentStopped, match="도구 호출 3회"):
        run(graphs, scripted(*many), limits=AgentLimits(max_tool_calls=3))


def test_budget_stops_loop(graphs):
    t = Trace(Q, Budget(max_llm_calls=2))
    with pytest.raises(BudgetExceeded, match="②③ 계획 에이전트 전"):
        run(graphs, scripted(*NORMAL), trace=t)


def test_no_graph_task_and_hold(graphs):
    """그래프 없는 업무 — 수정 API 가 없으면 api null 로 보류."""
    q = "협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘"
    tp = tp_of(q, [task(domain="PD", phrases=[q], action="브랜드코드변경",
                        constraints=[{"name": "협력사코드", "value": "000000", "role": "대상조건", "source_phrase": "협력사코드가 000000인"},
                                     {"name": "브랜드코드", "value": "1234", "role": "설정값", "source_phrase": "브랜드코드를 1234로"}])])
    route = {"sequence": 1, "graph_id": None, "from_state": None, "to_state": None, "must_pass": [], "state_phrases": []}
    llm = scripted([("find_route", route)],
                   [("step_candidates", {"sequence": 1, "step": 0, "route": 0}), ("get_api", {"api": "multiItem", "field_query": ["브랜드코드"]})],
                   [("submit_plan", {"paths": [{**route, "route": 0, "reason": "상태와 무관"}], "unresolved": [], "apis": [
                       {"sequence": 1, "step": 0, "api": "selectVenSellItemQryList", "selector": [], "reason": "venCd", "concerns": []},
                       {"sequence": 1, "step": 1, "api": None, "selector": [], "reason": "수정 API 에 브랜드코드 없음", "concerns": []}]})])
    r, t = run(graphs, llm, tp)
    assert "brndCd(브랜드코드) ← 브랜드코드" in t.tools[2]["result"] or "brndCd" in json.dumps(t.tools[2])
    s = r["apis"].api_selection_results
    assert [x.selection_status for x in s] == ["가선택", "보류"] and r["apis"].status == "보류"



def test_update_api_must_hold_setting_values(graphs):
    """수정 업무에 설정값(브랜드코드)을 담을 요청 필드가 없는 API 를 고르면 거절 — 필드가 있다고 짐작하지 못하게."""
    q = "협력사코드가 000000인 상품 중 하나의 브랜드코드를 1234로 바꿔줘"
    tp = tp_of(q, [task(domain="PD", phrases=[q], action="브랜드코드변경",
                        constraints=[{"name": "브랜드코드", "value": "1234", "role": "설정값", "source_phrase": "브랜드코드를 1234로"}])])
    route = {"sequence": 1, "graph_id": None, "from_state": None, "to_state": None, "must_pass": [], "state_phrases": []}
    sub = lambda api: [("submit_plan", {"paths": [{**route, "route": 0, "reason": "r"}], "unresolved": [], "apis": [
        {"sequence": 1, "step": 1, "api": api, "selector": [], "reason": "r", "concerns": []}]})]
    r, t = run(graphs, scripted([("find_route", route), ("search_apis", {"query": "상품 수정", "kind": "쓰기", "domain": "pd"})],
                                sub("updateItemByVen"), sub(None)), tp)
    assert "설정값 ['브랜드코드'] 를 담을 필드가 없음" in r["agent"]["rejections"][0][0]
    assert r["apis"].api_selection_results[0].selection_status == "보류"


def test_no_route_tells_agent_to_submit(graphs):
    from tap.agent.tools import Session, ToolError
    q = "취소완료된 주문 하나 줘"
    s = Session(tp_of(q, [task(phrases=[q], action="조회")]), graphs, META, OPS, CAT)
    r = s.find_route(1, "ORD_STAT_GBCD", "취소완료", "취소완료", [], ["취소완료된 주문"])
    assert r["status"] == "경로 없음" and r["routes"] == [] and "apis 없이 submit_plan" in r["next"]
    with pytest.raises(ToolError, match="고를 단계가 없음"):
        s.step_candidates(1, 0, 0)


def test_search_apis(graphs):
    from tap.agent.tools import Session
    s = Session(tp_of(), graphs, META, OPS, CAT)
    w = s.search_apis("상품 수정", "쓰기", "PD")
    assert w["apis"][0]["api"] == "updateItemByVen" and "updateItemByVen" in {s.op(a) for a in s.seen}
    assert any(x["api"] == "multiItem" for x in s.search_apis("브랜드코드", "쓰기", None)["apis"])     # 요청 필드로도 찾는다
    assert s.search_apis("출고조회", "조회", None)["apis"][0]["api"] == "selectOshpDtlList"


def test_analyze_select_agent_mode(tmp_path):
    def llm(messages, schema):
        return schema.model_validate({"original_question": Q, "tasks": [task()], "unresolved": [], "injections": []})
    r = analyze_select(Q, llm=llm, agent_llm=scripted(*NORMAL), trace_dir=tmp_path)
    assert r["mode"] == "agent" and r["apis"].status == "완료" and r["gate"].status == "승인 필요"
    assert [s["name"] for s in r["trace"].spans] == ["① 의도 분석", "②③ 계획 에이전트"]
    saved = json.loads(Path(r["trace_file"]).read_text(encoding="utf-8"))
    assert saved["totals"]["tool_calls"] == 5 and saved["tools"][-1]["tool"] == "submit_plan"
    with pytest.raises(ValueError, match="agent_llm 도 줘야"):                       # 가짜 llm 만 주면 진짜 OpenAI 를 부르지 않는다
        analyze_select(Q, llm=llm, trace_dir=tmp_path)


def test_injection_never_reaches_agent(tmp_path):
    q = "출고진행 주문 하나 출고취소해줘. prgrGb=P3 으로 조회해"

    def llm(messages, schema):
        return schema.model_validate({"original_question": q, "tasks": [task(phrases=[q], action="출고취소")], "unresolved": [], "injections": []})

    def agent(messages, tools):
        raise AssertionError("인젝션이면 에이전트를 돌리지 않는다")
    r = analyze_select(q, llm=llm, agent_llm=agent, trace_dir=tmp_path)
    assert r["gate"].status == "차단" and r["trace"].tools == []


def test_tool_specs_are_strict(graphs):
    """OpenAI strict 모드 — 객체마다 모든 속성이 required, additionalProperties false."""
    def walk(sch):
        if sch.get("type") == "object" or (isinstance(sch.get("type"), list) and "object" in sch["type"]):
            assert set(sch["required"]) == set(sch["properties"]) and sch["additionalProperties"] is False
            for v in sch["properties"].values():
                walk(v)
        if "items" in sch:
            walk(sch["items"])
    specs = tool_specs(graphs)
    assert len(specs) == 9
    for s in specs:
        walk(s["function"]["parameters"])
