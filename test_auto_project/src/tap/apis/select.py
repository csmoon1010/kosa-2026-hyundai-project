"""API 선택 — 경로(그래프 경로 탐색 결과)의 단계마다 API 하나 (+ 구분값)를 고른다.

① 후보 찾기 — API 카탈로그: 사용 중 · 종류(쓰기/조회) · 도메인으로 대상 API 를 추리고,
   화살표 이름 · 출발/도착 상태를 API 이름 · 별칭 · 구분값 이름과 맞춘다 (매칭기 tap.graph.match — 화면 미리보기와 같은 점수)
② 확정 검사 — API 메타데이터: 종류 · 사용 여부 · 구분값 필드가 요청에 있는지 · 값이 구분값 목록에 있는지 · 되돌림 불가
③ 고르기 — 통과 1개 / 1순위가 확실 → 규칙, 비슷한 후보 여럿 → LLM (후보 안에서만)
그래프는 노드 흐름만 갖는다 — 그래프 파일에 API 가 적혀 있어도 쓰지 않고 늘 여기서 고른다. 사람이 바로잡는 곳은 API Metadata(규칙 입력).

selection_status: 선택 · 가선택(사람 확인 필요) · 보류(고를 API 없음)
고른 API 는 시나리오 승인본(Scenario IR)에 고정한다 — 실행 때 다시 고르지 않는다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from tap.goal.extract import LLMParse, TaskPlan
from tap.graph.match import _CREATE, CHECK, FOUND, Candidate, match_edge, match_lookup, sim
from tap.graph.model import NEW, StateGraph
from tap.graph.paths import PathPlan, TaskPath

SCOPE = ["pd", "od", "ds"]                      # 1차 범위 — 후보를 찾는 도메인
MARGIN = 0.15                                   # 1순위가 2순위보다 이만큼 높으면 규칙이 고른다
TOP = 5
KIND_API = {"조회": "read", "상태변경": "write", "수정": "write"}
STATUS = ("선택", "가선택", "보류")


class ApiCandidate(BaseModel):
    api_id: str
    name: str
    selector: dict[str, str]
    score: float
    check: Literal["통과", "주의", "탈락"]
    check_reason: str | None = None


class Selected(BaseModel):
    api_id: str
    selector: dict[str, str]


class StepSelection(BaseModel):
    path_sequence: int
    step: int                                   # 0 = 출발 데이터 조회 (start_by 조회일 때)
    kind: Literal["조회", "상태변경", "수정"]
    domain: str
    edge: str
    from_: str | None = Field(alias="from")
    to: str | None
    api_candidates: list[ApiCandidate]
    selected: Selected | None
    selection_status: Literal[STATUS]  # type: ignore[valid-type]
    selected_by: Literal["규칙", "LLM"] | None
    selection_reason: str

    model_config = {"populate_by_name": True}


class Unresolved(BaseModel):
    path_sequence: int | None
    step: int | None
    reason: str


class ApiSelection(BaseModel):
    original_question: str
    status: Literal["완료", "검토 필요", "보류", "업무 없음", "차단"]
    api_selection_results: list[StepSelection]
    unresolved: list[Unresolved]

    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


# ─── ② 확정 검사 — API 메타데이터 ─────────────────────────────────────────────────────────

def check(c: Candidate, kind: str, meta: dict[str, dict[str, Any]], req: dict[str, set[str]],
          state_field: str | None) -> tuple[str, str | None]:
    """통과 · 주의(써도 되지만 사람 확인) · 탈락."""
    m = meta.get(c.api_id)
    if not m:
        return "탈락", "API Metadata 에 없음"
    if m["kind"] != KIND_API[kind]:
        return "탈락", f"{kind} 단계인데 API 가 {'조회' if m['kind'] == 'read' else '쓰기'}로 분류됨"
    if not m.get("tool_enabled", True):
        return "탈락", "사용 안 함(tool_enabled=false)"
    warn = []
    sels = {s["field"]: s for s in m.get("selectors") or []}
    for f, v in c.selector.items():
        if f not in req.get(c.api_id, set()):
            return "탈락", f"구분값 필드 {f} 가 요청에 없음"
        if v == "?":
            return "탈락", f"{f} 값을 모름 — 구분값 목록이 미완성, 개발 담당자 확인"
        if state_field and f.lower() in (state_field.lower(), state_field.lower() + "in"):
            continue                            # 상태 필드에 상태 코드를 바로 넣는 경우 — 구분값 목록과 무관
        s = sels.get(f)
        if s is None:
            warn.append(f"구분값 {f} 가 Metadata selectors 에 없음")
        elif v not in {x["value"] for x in s["values"]}:
            if s.get("complete"):
                return "탈락", f"{f}={v} 가 구분값 목록에 없음"
            warn.append(f"{f}={v} 는 구분값 목록(일부)에 없음")
    if m.get("irreversible") == "불가":
        warn.append("되돌릴 수 없는 API — 실행 전 사람 확인")
    return ("주의", " · ".join(warn)) if warn else ("통과", None)


# ─── 단계 만들기 · ① 후보 찾기 ────────────────────────────────────────────────────────────

def _field_hits(names: list[str], api_id: str, ops: dict[str, dict[str, Any]]) -> list[str]:
    """업무 용어(가격 · 협력사코드 …)가 요청 필드 이름 · 한글명과 맞는 것."""
    fields = ops.get(api_id, {}).get("request_fields") or []
    return [n for n in names if any(sim(n, f.get("label")) >= 0.8 or sim(n, f["name"]) >= 0.8 for f in fields)]


def _no_graph_candidates(kind: str, action: str, names: list[str], metadata: list[dict[str, Any]],
                         ops: dict[str, dict[str, Any]]) -> list[Candidate]:
    """그래프 없는 업무 — 업무 이름 · 업무 용어(제약 이름)로 찾는다. 명세만으로는 맞히기 어려워 결과는 늘 가선택."""
    out = []
    for m in metadata:
        if m["kind"] != KIND_API[kind] or not m.get("tool_enabled", True) or m["domain"] not in SCOPE:
            continue
        s = max(sim(action, m["api_name"]), *(sim(action, a) for a in m.get("aliases") or [""])) if kind == "수정" else 0.0
        hits = _field_hits(names, m["api_id"], ops)
        score = min(1.0, max(s, 0.0) * 0.6 + (0.6 * len(hits) / len(names) if names else 0.0))
        reasons = [f"요청 필드에 {', '.join(hits)}" if hits else f"이름 '{m['api_name']}'"]
        if kind == "수정" and m.get("action") in _CREATE:   # 새로 등록하는 API — 있는 데이터를 고치는 데는 맞지 않을 수 있다
            score *= 0.5
            reasons.append(f"새로 {m['action']}하는 API — 수정에는 맞지 않을 수 있음")
        if score >= 0.3:
            out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], score=round(score, 3), reasons=reasons))
    out.sort(key=lambda c: (-c.score, c.api_id))
    return out[:TOP]


def _steps_of(p: TaskPath, tp: TaskPlan, g: StateGraph | None, metadata: list[dict[str, Any]],
              operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """경로 하나 → 고를 단계들 (kind · edge · from · to · 후보)."""
    ops = {o["api_id"]: o for o in operations}
    out: list[dict[str, Any]] = []
    if g is None:                               # 그래프 없는 업무: 대상 찾기(대상조건이 있으면) + 수정
        task = next(t for t in tp.tasks if t.sequence == p.sequence)
        find = [c.name for c in task.constraints if c.role == "대상조건"]
        put = [c.name for c in task.constraints if c.role == "설정값"]
        if find:
            out.append({"step": 0, "kind": "조회", "edge": f"{task.action} 대상 찾기 ({', '.join(find)})", "from": None, "to": None,
                        "cands": _no_graph_candidates("조회", task.action, find, metadata, ops), "loose": True})
        out.append({"step": 1, "kind": "수정", "edge": task.action, "from": None, "to": None,
                    "cands": _no_graph_candidates("수정", task.action, put, metadata, ops), "loose": True})
        return out
    code = lambda name: NEW if name == NEW else g.code_of(name)
    if p.start_by == "조회" and p.from_state:
        c = code(p.from_state)
        node = g.node(c)
        out.append({"step": 0, "kind": "조회", "edge": f"{node.name} 데이터 찾기", "from": None, "to": node.name,
                    "cands": match_lookup(node.name, c, metadata, operations, g.state_field, SCOPE, top=TOP), "loose": False})
    for s in p.steps:
        a, b = code(s.from_), code(s.to)
        e = next((x for x in g.edges if (x.from_code, x.to_code, x.name) == (a, b, s.edge)), None)
        out.append({"step": s.step, "kind": "상태변경", "edge": s.edge, "from": s.from_, "to": s.to,
                    "cands": match_edge(s.edge, s.from_, s.to, metadata, SCOPE, top=TOP, operations=operations,
                                        state_field=g.state_field, to_code=b), "loose": False})
    return out


# ─── ③ 고르기 ────────────────────────────────────────────────────────────────────────────

def _rule_pick(st: dict[str, Any], passed: list[tuple[Candidate, str, str | None]]) -> dict[str, Any] | None:
    """규칙으로 고를 수 있으면 결과, 아니면 None (→ LLM)."""
    if not passed:
        return {"selected": None, "status": "보류", "by": None,
                "reason": "고를 API 가 없음 — " + ("후보 없음" if not st["cands"] else
                                                   f"후보가 모두 확정 검사에서 탈락했거나 점수가 낮음({CHECK} 미만)")}
    top, chk, why = passed[0]
    clear = len(passed) == 1 or top.score - passed[1][0].score >= MARGIN
    if not clear:
        return None
    sure = top.score >= FOUND and chk == "통과" and not st["loose"]
    reason = "; ".join(top.reasons) + (f" (주의: {why})" if why else "")
    if st["loose"]:
        reason += " — 그래프 없는 업무라 명세만으로 고름, 사람 확인"
    elif top.score < FOUND:
        reason += f" — 점수 {top.score:.2f} 로 낮음, 사람 확인"
    return {"selected": Selected(api_id=top.api_id, selector=top.selector), "status": "선택" if sure else "가선택",
            "by": "규칙", "reason": reason}


def _llm_block(key: str, st: dict[str, Any], passed: list[tuple[Candidate, str, str | None]], g: StateGraph | None,
               ops: dict[str, dict[str, Any]], meta: dict[str, dict[str, Any]]) -> str:
    head = f"- key {key} | {g.name + ' 그래프' if g else '그래프 없음'} | {st['kind']} | " \
           + (f"{st['from']} → {st['to']} " if st["from"] else (f"→ {st['to']} " if st["to"] else "")) + f"\"{st['edge']}\"" \
           + (f" | 상태 필드 {g.state_field}" if g and g.state_field else "")
    lines = [head]
    for i, (c, _, _) in enumerate(passed):
        m = meta.get(c.api_id, {})
        sel = " · ".join(f"{k}={v}" + (f" {c.action}" if c.action else "") for k, v in c.selector.items()) or "없음"
        fields = ", ".join(f"{f['name']}({f.get('label') or ''})" for f in (ops.get(c.api_id, {}).get("request_fields") or [])[:15])
        lines.append(f"  {chr(65 + i)}) {c.api_name} ({c.api_id.rsplit('/', 1)[-1]}) | {m.get('description') or ''} | 구분값 {sel} | 요청 필드: {fields}")
    return "\n".join(lines)


def pick_schema(keys: list[str], n: int) -> type[BaseModel]:
    Pick = create_model(
        "PickOut",
        key=(Literal[tuple(keys)], Field(description="고를 단계의 key")),  # type: ignore[valid-type]
        choice=(Literal[tuple(chr(65 + i) for i in range(n)) + ("없음",)], Field(description="후보 기호. 맞는 게 없으면 '없음'")),  # type: ignore[valid-type]
        reason=(str, Field(description="명세의 어떤 내용 때문에 골랐는지 한 문장")),
        concerns=(list[str], Field(description="고르기는 했지만 사람이 확인해야 할 점")),
    )
    return create_model("PicksOut", picks=(list[Pick], Field(description="단계마다 하나")))


def pick_messages(tp: TaskPlan, blocks: list[str]) -> list[dict[str, str]]:
    tasks = "\n".join(json.dumps({k: t.model_dump()[k] for k in ("sequence", "action", "conditions", "constraints")},
                                 ensure_ascii=False) for t in tp.tasks)
    system = f"""당신은 업무 단계마다 후보 API 중 하나를 고르는 역할만 한다. 후보 밖의 API 를 고르지 않는다.

[요청 원문]
{tp.original_question}

[업무]
{tasks}

[고를 단계 — key 는 '업무 sequence-단계 번호']
{chr(10).join(blocks)}

규칙
1. 단계의 출발 → 도착 상태 변화를 실제로 일으키는 API 를 고른다. 이름이 비슷해도 반대 동작(취소 · 반려)은 고르지 않는다.
   조회 단계는 그 상태의 데이터를 찾아 주는 API 를 고른다.
2. 업무의 설정값(constraints)을 요청에 담을 수 있는 API 를 우선한다. (예: 가격을 정해야 하면 가격 필드가 있는 API)
3. 맞는 후보가 없으면 "없음"을 고른다. 억지로 고르지 않는다.
4. 고르기는 했지만 사람이 확인해야 할 점이 있으면 concerns 에 적는다. (예: 설치상품에도 쓰이는지 명세에 없음)
5. reason 에 명세의 어떤 내용 때문에 골랐는지 한 문장으로 쓴다."""
    return [{"role": "system", "content": system}, {"role": "user", "content": "단계마다 API 를 골라 줘."}]


def select_apis(tp: TaskPlan, pp: PathPlan, graphs: list[StateGraph], metadata: list[dict[str, Any]],
                operations: list[dict[str, Any]], catalog: dict[str, Any] | None = None,
                llm: LLMParse | None = None) -> ApiSelection:
    """경로마다 단계별 API. 카탈로그에 없거나 사용 안 함인 API 는 후보에서 뺀다. 애매한 단계가 없으면 LLM 을 부르지 않는다."""
    if catalog is not None:                     # ① 카탈로그 = 후보로 쓸 수 있는 API 목록
        allowed = {a["api_id"] for a in catalog.get("apis") or [] if a.get("tool_enabled", True)}
        metadata = [m for m in metadata if m["api_id"] in allowed]
    meta = {m["api_id"]: m for m in metadata}
    ops = {o["api_id"]: o for o in operations}
    req = {o["api_id"]: {f["name"] for f in o["request_fields"]} for o in operations}
    by_id = {g.graph_id: g for g in graphs}
    rows: list[dict[str, Any]] = []
    unresolved: list[Unresolved] = []
    ask: list[tuple[str, dict[str, Any], list, StateGraph | None]] = []
    for p in pp.paths:
        if p.status == "경로 없음":
            unresolved.append(Unresolved(path_sequence=p.sequence, step=None, reason="경로 없음 — 경로 탐색 결과의 unresolved 참고"))
            continue
        g = by_id.get(p.graph_id or "")
        for st in _steps_of(p, tp, g, metadata, operations):
            sf = g.state_field if g else None
            judged = [(c, *check(c, st["kind"], meta, req, sf)) for c in st["cands"]]
            cands = [ApiCandidate(api_id=c.api_id, name=c.api_name, selector=c.selector, score=round(c.score, 3),
                                  check=k, check_reason=w) for c, k, w in judged]
            row = {"path_sequence": p.sequence, "step": st["step"], "kind": st["kind"], "domain": p.domain,
                   "edge": st["edge"], "from": st["from"], "to": st["to"], "api_candidates": cands}
            passed = [(c, k, w) for c, k, w in judged if k != "탈락" and c.score >= CHECK]   # 점수가 '없음' 기준 미만이면 보여 주기만
            passed.sort(key=lambda x: -x[0].score)
            r = _rule_pick(st, passed)
            if r is None:
                key = f"{p.sequence}-{st['step']}"
                ask.append((key, st, passed[:TOP], g))
                rows.append({**row, "_key": key, "_passed": passed[:TOP], "_loose": st["loose"]})
                continue
            rows.append({**row, "selected": r["selected"], "selection_status": r["status"], "selected_by": r["by"],
                         "selection_reason": r["reason"]})
            if r["status"] == "보류":
                unresolved.append(Unresolved(path_sequence=p.sequence, step=st["step"], reason=f"'{st['edge']}': {r['reason']}"))

    if ask:                                     # 애매한 단계만 한 번에 LLM 에
        if llm is None:
            raise ValueError("후보가 비슷한 단계가 있어 LLM 이 필요합니다")
        blocks = [_llm_block(k, st, ps, g, ops, meta) for k, st, ps, g in ask]
        out = llm(pick_messages(tp, blocks), pick_schema([k for k, *_ in ask], max(len(ps) for _, _, ps, _ in ask)))
        picks = {x["key"]: x for x in out.model_dump()["picks"]}
        for row in rows:
            if "_key" not in row:
                continue
            key, passed, loose = row.pop("_key"), row.pop("_passed"), row.pop("_loose")
            x = picks.get(key)
            i = ord(x["choice"]) - 65 if x and x["choice"] != "없음" else None
            if i is None or i >= len(passed):
                why = "LLM 이 맞는 후보가 없다고 함" + (f" — {x['reason']}" if x else " (답 없음)")
                row.update(selected=None, selection_status="보류", selected_by="LLM" if x else None, selection_reason=why)
                unresolved.append(Unresolved(path_sequence=row["path_sequence"], step=row["step"], reason=f"'{row['edge']}': {why}"))
                continue
            c, k, w = passed[i]
            concerns = list(x["concerns"]) + ([w] if w else []) + (["그래프 없는 업무라 명세만으로 고름"] if loose else [])
            row.update(selected=Selected(api_id=c.api_id, selector=c.selector), selected_by="LLM",
                       selection_status="가선택" if concerns else "선택",
                       selection_reason=x["reason"] + (f" (확인: {' · '.join(concerns)})" if concerns else ""))
            for cc in concerns:
                unresolved.append(Unresolved(path_sequence=row["path_sequence"], step=row["step"], reason=cc))

    results = [StepSelection.model_validate(r) for r in rows]
    for p in pp.paths:                          # 기본 경로에 보류가 있으면 — 모든 단계에 API 가 있는 대안 경로를 안내 (바꾸지는 않음)
        if not any(r.path_sequence == p.sequence and r.selection_status == "보류" for r in results):
            continue
        for alt in p.alternatives:
            ap = p.model_copy(update={"from_state": alt.from_state, "start_by": alt.start_by, "steps": alt.steps})
            ok = True
            for st in _steps_of(ap, tp, by_id.get(p.graph_id or ""), metadata, operations):
                g = by_id.get(p.graph_id or "")
                judged = [(c, *check(c, st["kind"], meta, req, g.state_field if g else None)) for c in st["cands"]]
                r = _rule_pick(st, sorted([x for x in judged if x[1] != "탈락" and x[0].score >= CHECK], key=lambda x: -x[0].score))
                ok = ok and r is not None and r["status"] != "보류"
            if ok:
                unresolved.append(Unresolved(path_sequence=p.sequence, step=None,
                                             reason=f"대안 경로({alt.from_state}에서 {alt.start_by}, {alt.why})는 모든 단계에 API 가 있음 — 대안으로 바꾸려면 확인"))
                break
    bad_path = any(p.status == "경로 없음" for p in pp.paths)
    status = "업무 없음" if not pp.paths else "보류" if bad_path or any(r.selection_status == "보류" for r in results) else \
        "검토 필요" if any(r.selection_status == "가선택" for r in results) else "완료"
    return ApiSelection(original_question=pp.original_question, status=status, api_selection_results=results,
                        unresolved=[_from_text(u) for u in pp.unresolved] + unresolved)


def _from_text(u: str) -> Unresolved:
    """경로 탐색의 unresolved('2번 업무: …') → 업무 번호를 살린다."""
    m = re.match(r"^(\d+)번 업무: ?(.*)$", u)
    return Unresolved(path_sequence=int(m.group(1)), step=None, reason=m.group(2)) if m else Unresolved(path_sequence=None, step=None, reason=u)
