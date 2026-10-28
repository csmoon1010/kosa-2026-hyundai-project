"""화살표 · 상태 → API 후보. 업무 담당자는 API 를 고르지 않는다 — API 지식(Metadata)에서 시스템이 찾는다.

후보 단위 = API + 구분값 하나 (구분값이 없는 API 는 API 자체가 한 단위).
  화살표 → 쓰기 API: 업무 이름(없으면 도착 상태 이름)을 구분값 이름 · 별칭 · API 이름과 맞춘다
  상태   → 조회 API: 응답에 상태 필드가 있는 조회 API 중, 요청에도 그 필드가 있으면 상태 코드로 바로 거르고
                    아니면 구분값 이름에서 상태 이름 · 코드를 찾는다
점수는 0~1. 최종 선택은 시나리오 등록 때 Agent 가 후보 중에서 하고 승인본에 고정한다.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from pydantic import BaseModel, Field

FOUND, CHECK = 0.75, 0.45                       # 이상이면 '찾음', 사이면 '확인 필요', 아래면 '없음'


class Candidate(BaseModel):
    api_id: str
    api_name: str
    selector: dict[str, str] = Field(default_factory=dict)   # 비어 있으면 구분값 없음
    action: str | None = None                   # 구분값 이름 (출고진행)
    score: float
    reasons: list[str] = Field(default_factory=list)
    selector_unknown: bool = False              # API 는 맞는데 구분값 목록이 미완성이라 값을 모름


def status_of(cands: list[Candidate]) -> str:
    """찾음 · 확인 필요 · 없음. 1순위와 같은 점수의 다른 API 가 있으면 고를 수 없으니 '확인 필요'."""
    if not cands or cands[0].score < CHECK:
        return "없음"
    tie = len(cands) > 1 and cands[1].api_id != cands[0].api_id and abs(cands[1].score - cands[0].score) < 1e-9
    return "찾음" if cands[0].score >= FOUND and not cands[0].selector_unknown and not tie else "확인 필요"


def _norm(s: str | None) -> str:
    s = re.sub(r"\([^)]*\)", "", s or "")       # '출고대기(25)만' → '출고대기만'
    return re.sub(r"[\s·,/\-_\[\]]+", "", s).removesuffix("처리").removesuffix("만")


def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


_REVERSE = ("취소", "반려", "철회", "삭제", "해제", "중지")   # 방향을 뒤집는 낱말
_CREATE = ("등록", "생성")                                    # 새로 만드는 동작 (API Metadata action)


def sim(a: str | None, b: str | None) -> float:
    """같으면 1, 한쪽이 다른 쪽을 품으면 0.8, 아니면 글자 쌍 겹침(Dice) × 0.7.

    '배송완료취소' 와 '배송완료' 처럼 방향을 뒤집는 낱말이 한쪽에만 있으면 반으로 깎는다 — 글자는 비슷해도 반대 동작이다.
    """
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    if x in y or y in x:
        base = 0.8 * (min(len(x), len(y)) / max(len(x), len(y))) ** 0.25
    else:
        bx, by = _bigrams(x), _bigrams(y)
        base = 0.7 * 2 * len(bx & by) / (len(bx) + len(by))
    if any((w in x) != (w in y) for w in _REVERSE):
        base *= 0.5
    return base


def _best(query: str, texts: Iterable[tuple[str, str]]) -> tuple[float, str]:
    best, why = 0.0, ""
    for label, t in texts:
        s = sim(query, t)
        if s > best:
            best, why = s, f"{label} '{t}'"
    return best, why


def _in_scope(m: dict[str, Any], kind: str, domains: list[str] | None) -> bool:
    return m["kind"] == kind and m.get("tool_enabled", True) and (not domains or m["domain"] in domains)


def _state_filter(fields: set[str], state_field: str | None) -> str | None:
    """요청에 상태 필드가 그대로(또는 목록 조건 …In 으로) 있으면 그 필드 이름."""
    if not state_field:
        return None
    return next((f for f in fields if f.lower() in (state_field.lower(), state_field.lower() + "in")), None)


def match_edge(name: str | None, from_name: str, to_name: str, metadata: list[dict[str, Any]],
               domains: list[str] | None = None, top: int = 3, operations: list[dict[str, Any]] | None = None,
               state_field: str | None = None, to_code: str | None = None) -> list[Candidate]:
    """화살표 하나의 쓰기 API 후보. name 은 업무 이름 (예: 출고완료취소), 없으면 도착 상태 이름으로 찾는다.

    쓰기 API 요청에 상태 필드가 그대로 있으면 (예: 상품 판매구분 변경 요청의 itemSellGbcd) 도착 상태 코드를 넣어
    바로 바꾸는 API 로 본다 — 이름이 안 맞아도 찾는다.
    """
    query = name or to_name
    req = {o["api_id"]: {f["name"] for f in o["request_fields"]} for o in operations or []}
    out: list[Candidate] = []
    for m in metadata:
        if not _in_scope(m, "write", domains):
            continue
        sf = _state_filter(req.get(m["api_id"], set()), state_field) if to_code else None
        if sf and sf == state_field:
            s, _ = _best(query, [("API 이름", m["api_name"])])
            if m.get("action") in _CREATE:              # 새로 만드는 API — 있는 데이터의 상태를 바꾸는 화살표에는 약하게
                out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], selector={sf: to_code}, score=0.6,
                                     reasons=[f"요청에 상태 필드 {sf} 가 있지만 새로 {m['action']}하는 API — 기존 데이터의 상태를 바꾸는 데는 맞지 않을 수 있음"]))
            else:
                out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], selector={sf: to_code},
                                     score=max(0.85, min(1.0, s + 0.1)),
                                     reasons=[f"요청에 상태 필드 {sf} 가 있어 도착 상태 코드 {to_code} 를 넣어 바로 바꿈"]))
            continue
        sels = m.get("selectors") or []
        api_texts = [("API 이름", m["api_name"])] + [("API 별칭", a) for a in m.get("aliases") or []]
        bonus = 0.08 if _norm(to_name) and _norm(to_name) in _norm(m.get("search_text")) else 0.0
        if not sels:
            s, why = _best(query, api_texts)
            out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], score=min(1.0, s + bonus),
                                 reasons=[f"{why} 과(와) 비슷함" if why else "이름이 비슷하지 않음"]))
            continue
        for sel in sels:
            for v in sel["values"]:
                texts = [("구분값 이름", v["name"])] if v.get("name") else []
                texts += [("구분값 별칭", a) for a in v.get("aliases") or []]
                s, why = _best(query, texts)
                if s < CHECK:                   # 구분값 이름이 안 맞으면 API 이름으로 한 번 더 (약하게)
                    s2, why2 = _best(query, api_texts)
                    if s2 * 0.8 > s:
                        s, why = s2 * 0.8, why2
                out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], selector={sel["field"]: v["value"]},
                                     action=v.get("name"), score=min(1.0, s + bonus),
                                     reasons=[f"{why} 과(와) 비슷함" if why else "이름이 비슷하지 않음"]
                                     + ([] if v.get("source") != "override" else ["사람이 확인한 구분값"])))
            if not sel.get("complete"):         # 값 목록이 미완성 — 이 API 의 다른 값일 수도 있다
                s, why = _best(query, api_texts + [("구분값 이름", v["name"]) for v in sel["values"] if v.get("name")])
                out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], selector={sel["field"]: "?"},
                                     score=min(1.0, s * 0.85 + bonus), selector_unknown=True,
                                     reasons=[f"{why} 과(와) 비슷함" if why else "이름이 비슷하지 않음",
                                              f"{sel['field']} 값 목록이 미완성 — 개발 담당자가 값을 확인해야 함"]))
    out.sort(key=lambda c: (-c.score, c.selector_unknown, c.api_id))
    return [c for c in out if c.score >= 0.3][:top]


def match_lookup(state_name: str, state_code: str, metadata: list[dict[str, Any]],
                 operations: list[dict[str, Any]], state_field: str | None,
                 domains: list[str] | None = None, top: int = 3) -> list[Candidate]:
    """상태 하나를 찾는 조회 API 후보. 응답에 상태 필드가 있는 조회 API 만 본다."""
    res = {o["api_id"]: {f["name"] for f in o["response_fields"]} for o in operations}
    req = {o["api_id"]: {f["name"] for f in o["request_fields"]} for o in operations}
    out: list[Candidate] = []
    for m in metadata:
        if not _in_scope(m, "read", domains) or (state_field and state_field not in res.get(m["api_id"], set())):
            continue
        sels = m.get("selectors") or []
        sf = _state_filter(req.get(m["api_id"], set()), state_field)
        if sf:                                                             # 요청에 같은 필드 → 상태 코드로 바로 거른다
            out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], selector={sf: state_code},
                                 score=0.9, reasons=[f"요청에 상태 필드 {sf} 가 있어 코드 {state_code} 로 바로 거름"]))
            continue
        if not sels:
            out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], score=0.35,
                                 reasons=[f"응답에 {state_field} 가 있지만 상태로 걸러 주는 값이 없음 — 전체를 조회해 골라야 함"]))
            continue
        for sel in sels:
            for v in sel["values"]:
                nm = v.get("name") or ""
                codes = re.findall(r"\d+", re.search(r"\(([^)]*)\)", nm).group(1)) if "(" in nm else []
                s, why = _best(state_name, [("구분값 이름", nm)] + [("구분값 별칭", a) for a in v.get("aliases") or []])
                reasons = [f"{why} 과(와) 비슷함"] if why else []
                if state_code in codes:
                    s = max(s, 0.9) if len(codes) == 1 else max(s, 0.8)
                    reasons.append(f"구분값 이름에 코드 {state_code} 가 있음" + ("" if len(codes) == 1 else " (다른 상태와 함께 조회)"))
                out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], selector={sel["field"]: v["value"]},
                                     action=nm or None, score=round(s, 3), reasons=reasons or ["이름이 비슷하지 않음"]))
            if not sel.get("complete"):         # 값을 모르면 API 이름에 상태 이름 일부가 있는지로만 가린다 (출고조회 ↔ 출고대기)
                out.append(Candidate(api_id=m["api_id"], api_name=m["api_name"], selector={sel["field"]: "?"},
                                     score=round(0.35 + 0.15 * sim(state_name, m["api_name"]), 3), selector_unknown=True,
                                     reasons=[f"응답에 {state_field} 가 있음", f"{sel['field']} 값 목록이 미완성 — 개발 담당자 확인"]))
    out.sort(key=lambda c: (-c.score, c.selector_unknown, c.api_id))
    return [c for c in out if c.score >= 0.3][:top]


def evaluate(gold: dict[str, Any], metadata: list[dict[str, Any]], operations: list[dict[str, Any]],
             domains: list[str] | None = None) -> dict[str, Any]:
    """정답 그래프의 화살표 이름 · 상태만 주고 API 를 맞히는지. 1순위가 (API, 구분값) 모두 같으면 정확."""
    codes = {str(k): v for k, v in gold["code_group"]["codes"].items()}
    rows = []
    for t in gold.get("transitions") or []:
        want = (t["api"], {k: str(v) for k, v in (t.get("selector") or {}).items()})
        cands = match_edge(t["name"], codes[str(t["from"])], codes[str(t["to"])], metadata, domains,
                           operations=operations, state_field=gold["graph"].get("state_field"), to_code=str(t["to"]))
        rows.append(_judge("전이", f"{t['from']}→{t['to']} {t['name']}", want, cands))
    for lk in gold.get("lookups") or []:
        want = (lk["api"], {k: str(v) for k, v in lk["selector"].items()})
        for s in lk["states"]:
            if str(s) not in codes:
                continue
            cands = match_lookup(codes[str(s)], str(s), metadata, operations, gold["graph"].get("state_field"), domains)
            rows.append(_judge("조회", f"{s} {codes[str(s)]}", want, cands))
    summary = {}
    for kind in ("전이", "조회"):
        r = [x for x in rows if x["kind"] == kind]
        summary[kind] = {"전체": len(r), "1순위 정확": sum(x["result"] == "정확" for x in r),
                         "3순위 안": sum(x["rank"] is not None for x in r),
                         "API만 맞음": sum(x["result"] == "API만 맞음" for x in r)}
    return {"summary": summary, "rows": rows}


def _judge(kind: str, item: str, want: tuple[str, dict[str, str]], cands: list[Candidate]) -> dict[str, Any]:
    rank = next((i + 1 for i, c in enumerate(cands) if (c.api_id, c.selector) == want), None)
    top = cands[0] if cands else None
    result = "후보 없음" if top is None else "정확" if (top.api_id, top.selector) == want \
        else "API만 맞음" if top.api_id == want[0] else "틀림"
    return {"kind": kind, "item": item, "result": result, "rank": rank, "status": status_of(cands),
            "want": f"{want[0].rsplit('/', 1)[-1]} {want[1]}",
            "top": [f"{c.api_id.rsplit('/', 1)[-1]} {c.selector} {c.action or ''} {c.score:.2f}" for c in cands]}
