"""API 선택 — 경로(그래프 경로 탐색 결과)의 단계마다 API 하나 (+ 구분값)를 고른다.

① 후보 찾기 — API 카탈로그: 사용 중 · 종류(쓰기/조회) · 도메인으로 대상 API 를 추리고,
   화살표 이름 · 출발/도착 상태를 API 이름 · 별칭 · 구분값 이름과 맞춘다 (매칭기 tap.graph.match — 화면 미리보기와 같은 점수)
② 확정 검사 — API 메타데이터: 종류 · 사용 여부 · 구분값 필드가 요청에 있는지 · 값이 구분값 목록에 있는지 · 되돌림 불가
   그래프 없는 업무는 업무 이름 · 업무 용어로 찾는다 (2026-11-11 점수 고침: 흔한 말을 빼고 동작 낱말을 맞춘 이름 비교 ·
   필드 한글명 뿌리 비교 — '가격수정' ↔ '상품 가격 수정 요청' · 가격 ↔ 매입가격)
③ 고르기 — 통과 1개 / 1순위가 확실 → 규칙, 비슷한 후보 여럿 → LLM (후보 안에서만)
   선택 · 가선택 규칙은 그래프 유무와 상관없이 같다 (2026-11-11). 그래프 없는 단계만 다른 점 하나:
   확정 기준(0.45) 이상 후보가 없으면 0.3 이상 후보로 LLM 에 묻는다 (보류 대신, 점수가 낮아 결과는 가선택)
   선택 = 점수 0.75 이상 · 확정 검사 통과 · (LLM 이 골랐으면) 확인 사항 없음. LLM 이 골라도 0.75 미만이면 가선택 (2026-11-12)
⑤ 행 상태값 — 고른 API 요청에 rowType · rowFlag 가 있으면 업무 동작으로 채운다 (신규 추가 INSERT · I / 수정 UPDATE · U / 삭제 DELETE · D)
④ 참조 조회 — 고른 쓰기 API 의 코드 필드(brndCd 브랜드코드)에 넣을 설정값이 이름("아디다스")이면, 이름으로 그 코드를
   찾아 주는 조회 API(요청에 브랜드명 · 응답에 brndCd)를 쓰기 앞 단계로 넣는다 → 단계 수는 고르기까지 끝나야 확정된다
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
from tap.graph.match import _CREATE, CHECK, FOUND, Candidate, is_row_field, match_edge, match_lookup, sim
from tap.graph.model import NEW, StateGraph
from tap.graph.paths import PathPlan, TaskPath

SCOPE = ["pd", "od", "ds"]                      # 1차 범위 — 후보를 찾는 도메인
MARGIN = 0.15                                   # 1순위가 2순위보다 이만큼 높으면 규칙이 고른다
TOP = 5
LOW = 0.3                                       # 그래프 없는 단계: 이 이상이면 후보로 보여 주고, 확정 기준(CHECK) 미만이어도 LLM 에 묻는다
KIND_API = {"조회": "read", "상태변경": "write", "수정": "write", "생성": "write"}
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


class Reference(BaseModel):
    """참조 조회 단계 — 쓰기 단계에 넣을 코드를 이름으로 찾는다 (2026-11-11)."""
    for_step: int                               # 이 조회 결과를 쓰는 쓰기 단계 번호 (같은 업무)
    term: str                                   # 업무 용어 (① constraints name — 브랜드코드)
    value: str                                  # 요청의 이름 값 (아디다스)
    code_field: str                             # 쓰기 요청의 코드 필드 (brndCd)
    name_field: str | None = None               # 조회 요청에 이름을 넣을 필드 (brndNm) — 고른 API 기준
    output_field: str | None = None             # 조회 응답에서 꺼낼 필드 (보통 code_field 와 같음)


class StepSelection(BaseModel):
    path_sequence: int
    step: int                                   # 0 = 출발 데이터 조회 (start_by 조회일 때)
    kind: Literal["조회", "상태변경", "수정", "생성"]
    domain: str
    edge: str
    from_: str | None = Field(alias="from")
    to: str | None
    api_candidates: list[ApiCandidate]
    selected: Selected | None
    selection_status: Literal[STATUS]  # type: ignore[valid-type]
    selected_by: Literal["규칙", "LLM"] | None
    selection_reason: str
    reference: Reference | None = None          # 참조 조회 단계만
    row_values: dict[str, str] = Field(default_factory=dict)   # 행 상태값 (rowType=INSERT · rowFlag=I) — 업무 동작으로 정함

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
    sels = {s["field"]: s for s in m.get("selectors") or [] if not is_row_field(s["field"])}   # 행 상태값은 구분값이 아니다
    for f, v in c.selector.items():
        if is_row_field(f):
            continue
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
    unset = [f for f in sels if f not in c.selector]
    if unset:                                   # API 에 구분값이 있는데 값을 정하지 않음 (그래프 없는 단계는 구분값을 맞추지 않는다)
        warn.append(f"구분값 {', '.join(unset)} 값을 정하지 않음 — 사람 확인")
    if m.get("irreversible") == "불가":
        warn.append("되돌릴 수 없는 API — 실행 전 사람 확인")
    return ("주의", " · ".join(warn)) if warn else ("통과", None)


# ─── 행 상태값 — 데이터셋에 행을 넣을 때 기본으로 채우는 값 (2026-11-11) ─────────────────────────────
# rowType: NORMAL · INSERT · UPDATE · DELETE / rowFlag: I · U · D. 메타데이터는 구분값으로 뽑지만(catalog/build) API 를
# 고르는 값이 아니라 요청의 동작(신규 추가 · 수정 · 삭제)에 따라 정해진다 → 선택과 따로 row_values 에 적는다.

ROW_VALUE = {"rowtype": {"I": "INSERT", "U": "UPDATE", "D": "DELETE"}, "rowflag": {"I": "I", "U": "U", "D": "D"}}
_DELETE = ("삭제", "제거")


def row_op(kind: str, action: str) -> str | None:
    """단계 동작 → I(신규 추가) · U(수정) · D(삭제). 조회는 없음.

    생성 단계는 I. 수정 · 상태변경은 업무 이름으로: 등록 · 생성 · 추가 … → I ('답변등록'은 있는 문의에 새 답변 행), 삭제 · 제거 → D, 그 밖은 U.
    """
    if kind == "조회":
        return None
    if kind == "생성":
        return "I"
    a = _key(action)                            # 같은 뜻 낱말을 대표 말(등록 · 수정)로
    return "D" if any(w in a for w in _DELETE) else "I" if "등록" in a else "U"


def row_values(api_id: str, kind: str, action: str, ops: dict[str, dict[str, Any]]) -> dict[str, str]:
    op = row_op(kind, action)
    if op is None:
        return {}
    names = dict.fromkeys(f["name"] for f in ops.get(api_id, {}).get("request_fields") or [] if is_row_field(f["name"]))
    return {n: ROW_VALUE[n.lower()][op] for n in names}


# ─── 단계 만들기 · ① 후보 찾기 ────────────────────────────────────────────────────────────

def term_hit(term: str, f: dict[str, Any]) -> bool:
    """업무 용어가 요청 필드 하나와 맞는가 — 비슷하거나(0.8 이상), 필드 한글명의 뿌리가 용어의 뿌리로 끝난다 (2026-11-11).

    뿌리 = 끝의 코드 · 명 · 이름을 뗀 것. 한국어 합성어는 끝 낱말이 중심이라 끝으로 비교한다:
    가격 → 매입가격 ✓ · 협력사 → 협력사코드 ✓ · 브랜드코드 → 브랜드코드 ✓ / 브랜드 → 바코드브랜드구분코드 ✗ · 가격 → 가격적용일자 ✗
    용어가 코드면 이름 필드와, 이름이면 코드 필드와는 맞추지 않는다 (협력사코드 → AS협력사명 ✗).
    """
    if sim(term, f.get("label")) >= 0.8 or sim(term, f["name"]) >= 0.8:
        return True
    b, t = _base(term), _clean(term)
    if t.endswith("코드") and _is_name(f) or t.endswith(("명", "이름")) and _is_code(f):
        return False
    return len(b) >= 2 and _base(f.get("label")).endswith(b)


def _field_hits(names: list[str], api_id: str, ops: dict[str, dict[str, Any]]) -> list[str]:
    """업무 용어(가격 · 협력사코드 …)가 요청 필드 이름 · 한글명과 맞는 것."""
    fields = ops.get(api_id, {}).get("request_fields") or []
    return [n for n in names if any(term_hit(n, f) for f in fields)]


VERBS = {"수정": ("변경", "바꾸기", "바꿈", "업데이트", "갱신"),   # 같은 뜻 동작 낱말 — 대표 말로 맞춰 비교
         "등록": ("생성", "만들기", "추가", "신규")}
GENERIC = ("상품", "요청")                       # API 이름에 흔한 말 — 빼고 비교 ('상품 가격 수정 요청' → 가격수정)


def _key(s: str | None) -> str:
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", s or "")
    s = re.sub(r"[\s·,/\-_]+", "", s)
    for rep, words in VERBS.items():
        for w in words:
            s = s.replace(w, rep)
    for w in GENERIC:
        s = s.replace(w, "")
    return s


def name_score(action: str, m: dict[str, Any]) -> float:
    """업무 이름 ↔ API 이름 · 별칭. 원래 글자 그대로와, 흔한 말을 빼고 동작 낱말을 맞춘 뒤 중 높은 쪽 (2026-11-11).

    '가격수정' ↔ '상품 가격 수정 요청': 그대로 0.67 → 맞춘 뒤 가격수정 = 가격수정 1.0.
    맞춘 뒤 한쪽이 동작 낱말만 남으면('상품 수정' → 수정) 대상이 없어 맞춘 비교는 쓰지 않는다.
    """
    best = 0.0
    for name in [m["api_name"], *(m.get("aliases") or [])]:
        s = sim(action, name)
        a, n = _key(action), _key(name)
        if a and n and a not in VERBS and n not in VERBS:
            s = max(s, sim(a, n))
        best = max(best, s)
    return best


def _no_graph_candidates(kind: str, action: str, names: list[str], metadata: list[dict[str, Any]],
                         ops: dict[str, dict[str, Any]]) -> list[Candidate]:
    """그래프 없는 업무 — 업무 이름 · 업무 용어(제약 이름)로 찾는다. 선택 · 가선택은 그래프 있는 단계와 같은 규칙(점수 · 확정 검사).

    수정: 이름 0.6 + 업무 용어 0.4 (생성과 같은 비중. 후보가 쓰기 API 전체라 생성의 기본 0.2 는 근거가 안 돼 두지 않는다)
    조회: 업무 용어(찾을 조건)만 0.6 — 업무 이름은 쓰기 동작이라 조회 API 이름과 맞출 수 없다
    """
    out = []
    for m in metadata:
        if m["kind"] != KIND_API[kind] or not m.get("tool_enabled", True) or m["domain"] not in SCOPE:
            continue
        hits = _field_hits(names, m["api_id"], ops)
        ratio = len(hits) / len(names) if names else 0.0
        if kind == "수정":
            s = name_score(action, m)
            score = min(1.0, 0.6 * s + 0.4 * ratio)
        else:
            score = min(1.0, 0.6 * ratio)
        reasons = [f"이름 '{m['api_name']}'"] if kind == "수정" else []
        reasons += [f"요청 필드에 {', '.join(hits)}"] if hits else []
        if kind == "수정" and m.get("action") in _CREATE:   # 새로 등록하는 API — 있는 데이터를 고치는 데는 맞지 않을 수 있다
            score *= 0.5
            reasons.append(f"새로 {m['action']}하는 API — 수정에는 맞지 않을 수 있음")
        if score >= LOW:
            out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], score=round(score, 3), reasons=reasons or [f"이름 '{m['api_name']}'"]))
    out.sort(key=lambda c: (-c.score, c.api_id))
    return out[:TOP]


CREATE_WORDS = VERBS["등록"]                     # 업무 이름의 '새로 만듦' 낱말 — API 이름 쪽 말(등록)로 맞춰 비교


def _create_candidates(action: str, names: list[str], domain: str, metadata: list[dict[str, Any]],
                       ops: dict[str, dict[str, Any]]) -> list[Candidate]:
    """그래프 없는 신규 업무 — 새로 만드는 쓰기 API(Metadata action 등록 · 생성)만 후보로 (2026-11-06).

    업무 도메인에 그런 API 가 있으면 그 도메인 것만 본다. 점수 = 0.2(새로 만드는 API) + 이름 0.6 + 업무 용어 0.4.
    """
    act = action
    for w in CREATE_WORDS:
        act = act.replace(w, "등록")
    pool = [m for m in metadata if m["kind"] == "write" and m.get("tool_enabled", True) and m["domain"] in SCOPE
            and any(w in (m.get("action") or "") for w in _CREATE)]
    pool = [m for m in pool if m["domain"] == domain.lower()] or pool
    out = []
    for m in pool:
        s = name_score(act, m)
        hits = _field_hits(names, m["api_id"], ops)
        score = min(1.0, 0.2 + 0.6 * max(s, 0.0) + (0.4 * len(hits) / len(names) if names else 0.0))
        reasons = [f"새로 {m['action']}하는 API", f"이름 '{m['api_name']}'"] + ([f"요청 필드에 {', '.join(hits)}"] if hits else [])
        if score >= LOW:
            out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], score=round(score, 3), reasons=reasons))
    out.sort(key=lambda c: (-c.score, c.api_id))
    return out[:TOP]


def _steps_of(p: TaskPath, tp: TaskPlan, g: StateGraph | None, metadata: list[dict[str, Any]],
              operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """경로 하나 → 고를 단계들 (kind · edge · from · to · 후보)."""
    ops = {o["api_id"]: o for o in operations}
    out: list[dict[str, Any]] = []
    if g is None:                               # 그래프 없는 업무: 신규는 생성 하나, 기존은 대상 찾기(대상조건이 있으면) + 수정
        task = next(t for t in tp.tasks if t.sequence == p.sequence)
        find = [c.name for c in task.constraints if c.role == "대상조건"]
        put = [c.name for c in task.constraints if c.role == "설정값"]
        if task.origin == "신규":                # 찾을 데이터가 없다 — 새로 만드는 API 를 바로 고른다
            if "수정" not in _key(task.action):
                return [{"step": 1, "kind": "생성", "edge": task.action, "from": None, "to": None,
                         "cands": _create_candidates(task.action, put, p.domain, metadata, ops), "loose": True}]
            # 만든 뒤 고치는 업무('가격수정' — 5000원으로 만들고 8000원으로 수정, 2026-11-12): 생성 → 수정 두 단계.
            # ① 은 같은 대상이면 업무 하나로 둔다. 생성 단계는 업무 이름이 수정이라 이름 대신 '등록'으로 찾는다
            return [{"step": 1, "kind": "생성", "edge": f"{task.action} 전에 새로 등록", "from": None, "to": None,
                     "cands": _create_candidates("등록", put, p.domain, metadata, ops), "loose": True},
                    {"step": 2, "kind": "수정", "edge": task.action, "from": None, "to": None,
                     "cands": _no_graph_candidates("수정", task.action, put, metadata, ops), "loose": True}]
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
    sure = top.score >= FOUND and chk == "통과"  # 그래프 있는 단계 · 없는 단계 같은 규칙 (2026-11-11 — 전엔 그래프 없으면 늘 가선택)
    reason = "; ".join(top.reasons) + (f" (주의: {why})" if why else "")
    if top.score < FOUND:
        reason += f" — 점수 {top.score:.2f} 로 낮음, 사람 확인"
    return {"selected": Selected(api_id=top.api_id, selector=top.selector), "status": "선택" if sure else "가선택",
            "by": "규칙", "reason": reason}


FIELDS_SHOWN = 15


def _show_fields(fields: list[dict[str, Any]], terms: list[str]) -> str:
    """LLM 에 보여 줄 요청 필드 — 업무 용어(제약 이름)와 맞는 필드를 먼저, 남는 자리는 명세 순서대로.

    필드가 수백 개인 API(상품 등록 244개)는 앞에서 자르면 정작 필요한 필드(brndCd 119번째)가 빠진다.
    """
    seen: dict[str, str] = {}                   # 이름 → 표시 (데이터셋이 달라도 같은 이름은 한 번)
    strong = lambda t, f: f["name"] == t or sim(t, f.get("label")) >= 0.8 or sim(t, f["name"]) >= 0.8
    for match in (strong, term_hit):            # 거의 같은 필드 먼저, 뿌리만 맞는 필드(매입가격 ← 가격)는 그다음
        for t in terms:
            for f in fields:
                if f["name"] not in seen and match(t, f):
                    seen[f["name"]] = f"{f['name']}({f.get('label') or ''}) ← {t}"
    for f in fields:
        if len(seen) >= FIELDS_SHOWN:
            break
        seen.setdefault(f["name"], f"{f['name']}({f.get('label') or ''})")
    rest = len({f["name"] for f in fields}) - len(seen)
    return ", ".join(seen.values()) + (f" … 외 {rest}개" if rest > 0 else "")


def _llm_block(key: str, st: dict[str, Any], passed: list[tuple[Candidate, str, str | None]], g: StateGraph | None,
               ops: dict[str, dict[str, Any]], meta: dict[str, dict[str, Any]]) -> str:
    head = f"- key {key} | {g.name + ' 그래프' if g else '그래프 없음'} | {st['kind']} | " \
           + (f"{st['from']} → {st['to']} " if st["from"] else (f"→ {st['to']} " if st["to"] else "")) + f"\"{st['edge']}\"" \
           + (f" | 상태 필드 {g.state_field}" if g and g.state_field else "")
    lines = [head]
    for i, (c, _, _) in enumerate(passed):
        m = meta.get(c.api_id, {})
        sel = " · ".join(f"{k}={v}" + (f" {c.action}" if c.action else "") for k, v in c.selector.items()) or "없음"
        fields = _show_fields(ops.get(c.api_id, {}).get("request_fields") or [], st.get("terms") or [])
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
   요청 필드의 '← 용어' 표시는 그 업무 용어와 맞는 필드다. 요청 필드는 일부만 보이고 나머지는 '외 N개'로 줄였다.
3. 맞는 후보가 없으면 "없음"을 고른다. 억지로 고르지 않는다.
4. 고르기는 했지만 사람이 확인해야 할 점이 있으면 concerns 에 적는다. (예: 설치상품에도 쓰이는지 명세에 없음)
5. reason 에 명세의 어떤 내용 때문에 골랐는지 한 문장으로 쓴다."""
    return [{"role": "system", "content": system}, {"role": "user", "content": "단계마다 API 를 골라 줘."}]


def _ask_llm(ask: list, rows: list[dict[str, Any]], tp: TaskPlan, ops: dict[str, dict[str, Any]],
             meta: dict[str, dict[str, Any]], llm: LLMParse | None, unresolved: list[Unresolved]) -> None:
    """규칙으로 못 고른 단계(ask)를 한 번에 LLM 에 — 후보 안에서만 고른다. rows 의 '_key' 행을 채운다."""
    if not ask:
        return
    if llm is None:
        raise ValueError("후보가 비슷한 단계가 있어 LLM 이 필요합니다")
    blocks = [_llm_block(k, st, ps, g, ops, meta) for k, st, ps, g in ask]
    out = llm(pick_messages(tp, blocks), pick_schema([k for k, *_ in ask], max(len(ps) for _, _, ps, _ in ask)))
    picks = {x["key"]: x for x in out.model_dump()["picks"]}
    for row in rows:
        if "_key" not in row:
            continue
        key, passed, low = row.pop("_key"), row.pop("_passed"), row.pop("_low", False)
        row.pop("_loose", None)
        x = picks.get(key)
        i = ord(x["choice"]) - 65 if x and x["choice"] != "없음" else None
        if i is None or i >= len(passed):
            why = "LLM 이 맞는 후보가 없다고 함" + (f" — {x['reason']}" if x else " (답 없음)")
            row.update(selected=None, selection_status="보류", selected_by="LLM" if x else None, selection_reason=why)
            unresolved.append(Unresolved(path_sequence=row["path_sequence"], step=row["step"], reason=f"'{row['edge']}': {why}"))
            continue
        c, k, w = passed[i]
        concerns = list(x["concerns"]) + ([w] if w else []) \
            + ([f"점수 {c.score:.2f} — 확정 기준({CHECK}) 미만 후보 중에서 고름"] if low else
               [f"점수 {c.score:.2f} — 선택 기준({FOUND}) 미만, 사람 확인"] if c.score < FOUND else [])   # 규칙과 같은 기준 (2026-11-12)
        row.update(selected=Selected(api_id=c.api_id, selector=c.selector), selected_by="LLM",
                   selection_status="가선택" if concerns else "선택",
                   selection_reason=x["reason"] + (f" (확인: {' · '.join(concerns)})" if concerns else ""))
        for cc in concerns:
            unresolved.append(Unresolved(path_sequence=row["path_sequence"], step=row["step"], reason=cc))


# ─── ④ 참조 조회 — 쓰기에 넣을 코드를 이름으로 찾는 조회 (2026-11-11) ─────────────────────────────

WRITE_KINDS = ("생성", "수정", "상태변경")
_SUFFIXES = ("코드", "이름", "명", "code", "name", "cd", "nm")


def _clean(s: str | None) -> str:
    return re.sub(r"[\s\"'“”‘’·_\-]+", "", s or "")


def _base(term: str | None) -> str:
    """업무 용어 · 필드 한글명의 뿌리 — 브랜드코드 · 브랜드명 · 브랜드 → 브랜드."""
    s = _clean(term).lower()
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _is_code(f: dict[str, Any]) -> bool:
    return bool(re.search(r"(Cd|CD|Code|CODE)$", f["name"])) or _clean(f.get("label")).endswith("코드")


def _is_name(f: dict[str, Any]) -> bool:
    return bool(re.search(r"(Nm|NM|Name|NAME)$", f["name"])) or _clean(f.get("label")).endswith(("명", "이름"))


def looks_like_name(value: str | None) -> bool:
    """코드가 아니라 이름인 값 — 한글이 있거나 숫자가 하나도 없다 ("아디다스" · "Nike"). "1234" · "B001" 은 코드."""
    v = _clean(value)
    return bool(v) and (bool(re.search(r"[가-힣]", v)) or not re.search(r"\d", v))


def code_field(term: str, api_id: str, ops: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """쓰기 API 요청에서 업무 용어에 맞는 코드 필드 (브랜드코드 · 브랜드 → brndCd(브랜드코드))."""
    b = _base(term)
    if not b:
        return None
    return next((f for f in ops.get(api_id, {}).get("request_fields") or [] if _is_code(f) and _base(f.get("label")) == b), None)


def ref_candidates(term: str, field: str, metadata: list[dict[str, Any]],
                   ops: dict[str, dict[str, Any]]) -> tuple[list[Candidate], dict[str, tuple[str, str]]]:
    """이름으로 코드를 찾아 주는 조회 API — 요청에 이름 필드(브랜드명) · 응답에 그 코드 필드(brndCd)가 둘 다 있어야 한다.

    명세 근거가 둘이라 기본 0.75(찾음), API 이름이 '브랜드 조회'에 가까울수록 더한다. 돌려주는 표: api_id → (이름 필드, 출력 필드).
    """
    b = _base(term)
    out, fields = [], {}
    for m in metadata:
        if m["kind"] != "read" or not m.get("tool_enabled", True) or m["domain"] not in SCOPE:
            continue
        o = ops.get(m["api_id"]) or {}
        res = o.get("response_fields") or []
        got = next((f for f in res if f["name"] == field), None) or \
            next((f for f in res if _is_code(f) and _base(f.get("label")) == b), None)
        name = next((f for f in o.get("request_fields") or [] if _is_name(f) and _base(f.get("label") or f["name"]) == b), None)
        if got is None or name is None:
            continue
        score = min(1.0, 0.75 + 0.25 * sim(b + "조회", m["api_name"]))
        out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], score=round(score, 3),
                             reasons=[f"요청에 {name['name']}({name.get('label') or ''}) — 이름으로 찾음",
                                      f"응답에 {got['name']}({got.get('label') or ''})"]))
        fields[m["api_id"]] = (name["name"], got["name"])
    out.sort(key=lambda c: (-c.score, c.api_id))
    return out[:TOP], fields


def _add_references(rows: list[dict[str, Any]], tp: TaskPlan, metadata: list[dict[str, Any]],
                    ops: dict[str, dict[str, Any]], meta: dict[str, dict[str, Any]], req: dict[str, set[str]]):
    """쓰기 단계마다: 설정값이 이름이고 고른 API 에 그 코드 필드가 있으면 참조 조회 단계를 바로 앞에 넣는다.

    업무 안의 단계 번호를 1부터 다시 매긴다 (0번 출발 데이터 조회는 그대로). 설정값 하나는 한 번만 (처음 맞는 쓰기 단계).
    돌려줌: 새 행 목록 · LLM 에 물을 참조 단계 · 옛 번호 → 새 번호 · 참조 단계의 미해결.
    """
    tasks = {t.sequence: t for t in tp.tasks}
    out: list[dict[str, Any]] = []
    ask: list = []
    remap: dict[tuple[int, int], int] = {}
    unresolved: list[Unresolved] = []
    groups: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["path_sequence"], []).append(r)
    for seq, group in groups.items():
        task = tasks.get(seq)
        # 신규 업무엔 찾을 기존 데이터가 없다 — ① 이 대상조건으로 적어도("…코드를 조회하고") 새 데이터에 넣을 값으로 본다
        todo = [c for c in (task.constraints if task else [])
                if (c.role == "설정값" or task.origin == "신규") and looks_like_name(c.value)]
        n = 0
        for r in group:
            if r["step"] == 0:
                remap[(seq, 0)] = 0
                out.append(r)
                continue
            refs = []
            sel = r.get("selected")
            if r["kind"] in WRITE_KINDS and sel is not None:
                for c in list(todo):
                    f = code_field(c.name, sel.api_id, ops)
                    if f:
                        refs.append((c, f))
                        todo.remove(c)
            write_no = n + len(refs) + 1
            for c, f in refs:
                n += 1
                value = c.value.strip(" \"'“”‘’") or c.value              # ① 이 따옴표째 적기도 한다 ("\"아디다스\"")
                cands, fields = ref_candidates(c.name, f["name"], metadata, ops)
                st = {"kind": "조회", "edge": f"{c.name} 찾기 — 이름 '{value}'로 조회해 {f['name']} 를 {seq}-{write_no} 에 넘김",
                      "from": None, "to": None, "cands": cands, "loose": False, "terms": [c.name]}
                judged = [(x, *check(x, "조회", meta, req, None)) for x in cands]
                row = {"path_sequence": seq, "step": n, "kind": "조회", "domain": r["domain"], "edge": st["edge"],
                       "from": None, "to": None, "_names": fields,
                       "reference": Reference(for_step=write_no, term=c.name, value=value, code_field=f["name"]),
                       "api_candidates": [ApiCandidate(api_id=x.api_id, name=x.api_name, selector=x.selector, score=x.score,
                                                       check=k, check_reason=w) for x, k, w in judged]}
                passed = sorted([x for x in judged if x[1] != "탈락" and x[0].score >= CHECK], key=lambda x: -x[0].score)
                pick = _rule_pick(st, passed)
                if pick is None:
                    key = f"{seq}-{n}"
                    ask.append((key, st, passed[:TOP], None))
                    out.append({**row, "_key": key, "_passed": passed[:TOP], "_loose": False})
                    continue
                if pick["status"] == "보류":
                    pick["reason"] = f"'{value}'를 {f['name']} 코드로 바꿀 조회 API 가 없음 — 코드를 직접 주거나 개발 담당자 확인"
                    unresolved.append(Unresolved(path_sequence=seq, step=n, reason=f"'{c.name}': {pick['reason']}"))
                out.append({**row, "selected": pick["selected"], "selection_status": pick["status"], "selected_by": pick["by"],
                            "selection_reason": pick["reason"]})
            n += 1
            remap[(seq, r["step"])] = n
            out.append({**r, "step": n})
    return out, ask, remap, unresolved


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
        task = next((t for t in tp.tasks if t.sequence == p.sequence), None)
        cons = task.constraints if task else []
        for st in _steps_of(p, tp, g, metadata, operations):
            sf = g.state_field if g else None
            st["terms"] = [c.name for c in cons if (c.role == "대상조건") == (st["kind"] == "조회")]   # 조회는 찾을 조건, 쓰기는 바꿀 값
            judged = [(c, *check(c, st["kind"], meta, req, sf)) for c in st["cands"]]
            cands = [ApiCandidate(api_id=c.api_id, name=c.api_name, selector=c.selector, score=round(c.score, 3),
                                  check=k, check_reason=w) for c, k, w in judged]
            row = {"path_sequence": p.sequence, "step": st["step"], "kind": st["kind"], "domain": p.domain,
                   "edge": st["edge"], "from": st["from"], "to": st["to"], "api_candidates": cands}
            passed = [(c, k, w) for c, k, w in judged if k != "탈락" and c.score >= CHECK]   # 점수가 '없음' 기준 미만이면 보여 주기만
            passed.sort(key=lambda x: -x[0].score)
            low = False
            if not passed and st["loose"] and llm is not None:   # 그래프 없는 단계: 확정 기준 미만(LOW 이상) 후보는 보류 대신 LLM 에
                passed = sorted([x for x in judged if x[1] != "탈락"], key=lambda x: -x[0].score)
                low = bool(passed)
            r = None if low else _rule_pick(st, passed)
            if r is None:
                key = f"{p.sequence}-{st['step']}"
                ask.append((key, st, passed[:TOP], g))
                rows.append({**row, "_key": key, "_passed": passed[:TOP], "_loose": st["loose"], "_low": low})
                continue
            rows.append({**row, "selected": r["selected"], "selection_status": r["status"], "selected_by": r["by"],
                         "selection_reason": r["reason"]})
            if r["status"] == "보류":
                unresolved.append(Unresolved(path_sequence=p.sequence, step=st["step"], reason=f"'{st['edge']}': {r['reason']}"))

    _ask_llm(ask, rows, tp, ops, meta, llm, unresolved)    # 애매한 단계만 한 번에 LLM 에

    rows, ref_ask, remap, ref_unresolved = _add_references(rows, tp, metadata, ops, meta, req)
    for u in unresolved:                        # 참조 조회가 끼어 단계 번호가 밀렸으면 미해결도 같이
        if u.step is not None and (u.path_sequence, u.step) in remap:
            u.step = remap[(u.path_sequence, u.step)]
    unresolved += ref_unresolved
    _ask_llm(ref_ask, rows, tp, ops, meta, llm, unresolved)
    for row in rows:                            # 참조 조회: 고른 API 의 이름 · 출력 필드를 적는다
        names = row.pop("_names", None)
        if names is not None and row.get("selected") is not None:
            row["reference"].name_field, row["reference"].output_field = names[row["selected"].api_id]
    actions = {t.sequence: t.action for t in tp.tasks}
    for row in rows:                            # 행 상태값: 고른 API 요청에 rowType · rowFlag 가 있으면 업무 동작으로 채운다
        sel = row.get("selected")
        if sel is not None:
            sel.selector = {k: v for k, v in sel.selector.items() if not is_row_field(k)}
            row["row_values"] = row_values(sel.api_id, row["kind"], actions.get(row["path_sequence"], ""), ops)

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
