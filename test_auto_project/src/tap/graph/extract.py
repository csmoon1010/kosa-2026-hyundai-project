"""그래프 재료 자동 추출 (실험) — 공통코드 테이블(노드) + 명세(API)만 주고 LLM 이 간선 · 조회 방법을 제안한다.

사람이 확인한 data/knowledge/*.yaml 을 정답지로 삼아 score.py 로 채점한다.
- 상태 코드 · api_id 는 목록(Literal) 안에서만 고른다 — 없는 코드 · API 를 지어내지 못한다
- 근거(basis)를 스스로 밝힌다: spec(명세에 글자로 적힘) · guess(이름 · 순서로 추측)
- 결과는 knowledge 형식 dict — 사람이 쓴 yaml 과 같은 형식이라 graph_from_dict 로 바로 그래프가 된다
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from tap.goal.extract import LLMParse


def load_code_table(path: str | Path, group_id: str) -> dict[str, Any]:
    """공통코드 테이블 export(CSV) 에서 코드 그룹 하나. 사용여부 Y 만, 정렬순서대로."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["코드그룹ID"] == group_id and r.get("사용여부", "Y") == "Y"]
    if not rows:
        raise ValueError(f"코드 그룹 {group_id} 가 {path} 에 없습니다")
    rows.sort(key=lambda r: int(r.get("정렬순서") or 0))
    return {"id": group_id, "name": rows[0]["코드그룹명"], "codes": {r["코드값"]: r["코드명"] for r in rows}}


def _field(f: dict[str, Any]) -> str:
    label = f.get("label") or ""
    ex = f.get("example")
    return f"{f['name']}({label}{', 예:' + str(ex) if ex not in (None, '') else ''})"


def spec_digest(operations: list[dict[str, Any]], metadata: list[dict[str, Any]]) -> str:
    """명세 전체를 API 마다 몇 줄로 줄인다. 쓰기/조회 구분은 1단계 Metadata 에서."""
    kind = {m["api_id"]: m["kind"] for m in metadata}
    out = []
    for o in operations:
        out.append(f"## {o['api_id']} | {kind.get(o['api_id'], '?')} | {o['summary']}"
                   + (f" | {o['description']}" if o.get("description") and o["description"] != o["summary"] else ""))
        out.append("  요청: " + ", ".join(_field(f) for f in o["request_fields"]))
        out.append("  응답: " + ", ".join(_field(f) for f in o["response_fields"]))
    return "\n".join(out)


def extract_schema(codes: dict[str, str], api_ids: list[str]) -> type[BaseModel]:
    Code = Literal[tuple(codes)]  # type: ignore[valid-type]
    Api = Literal[tuple(api_ids)]  # type: ignore[valid-type]
    Basis = Literal["spec", "guess"]
    Transition = create_model(
        "Transition",
        api_id=(Api, ...),
        selector_field=(str | None, Field(None, description="한 API 가 여러 동작을 할 때 동작을 고르는 요청 필드 (예: 처리구분)")),
        selector_value=(str | None, Field(None, description="그 필드의 값")),
        name=(str, Field(description="동작 이름")),
        from_code=(Code, Field(description="이 동작을 할 수 있는 전제 상태")),
        to_code=(Code, Field(description="동작 후 상태")),
        basis=(Basis, ...),
        evidence=(str, Field(description="판단 근거 — 명세 문구 그대로, 추측이면 추측한 이유")),
    )
    LookupOut = create_model(
        "LookupOut",
        api_id=(Api, ...),
        selector_field=(str | None, None),
        selector_value=(str | None, None),
        states=(list[Code], Field(description="이 조회로 나오는 (마지막) 상태들")),
        basis=(Basis, ...),
        evidence=(str, ...),
    )
    return create_model(
        "GraphOut",
        entity=(str, Field(description="상태를 가진 대상 (예: 주문, 상품)")),
        state_field=(str | None, Field(description="조회 응답에서 이 코드 그룹의 마지막 상태가 담기는 필드명")),
        entry_states=(list[Code], Field(description="외부(고객 주문 · 결제 등)에서 생기고 API 로 처음 다룰 수 있는 상태")),
        verify_key_fields=(list[str], Field(description="같은 데이터를 다시 찾는 키 필드")),
        transitions=(list[Transition], Field(default_factory=list)),
        lookups=(list[LookupOut], Field(default_factory=list)),
        open_questions=(list[str], Field(default_factory=list, description="자료만으로 정할 수 없어 사람에게 물어야 할 것")),
    )


def build_messages(code_group: dict[str, Any], digest: str) -> list[dict[str, str]]:
    codes = "\n".join(f"- {c} {n}" for c, n in code_group["codes"].items())
    system = f"""당신은 상태 전이 그래프의 재료를 만드는 역할이다. 아래 두 자료만 보고 판단한다.

[자료 1] 공통코드 — {code_group['id']} {code_group['name']} (정렬 순서대로)
{codes}

[자료 2] API 명세 요약 — api_id | 쓰기/조회 | summary | description, 요청 · 응답 필드 (필드명(한글명, 예:값))
{digest}

할 일
1. transitions: 이 코드 그룹의 상태를 바꾸는 쓰기 API 동작. 동작마다 api_id, 동작을 고르는 선택값 필드 · 값(있으면),
   전제 상태 → 결과 상태. 한 API 가 선택값에 따라 여러 동작을 하면 동작마다 따로 적는다.
2. lookups: 특정 상태의 데이터를 찾는 조회 API + 선택값 → 그 조회로 나오는 상태들.
3. state_field: 조회 응답에서 이 코드 그룹의 현재(마지막) 상태가 담기는 필드명.
4. entry_states: 외부(고객 주문 · 결제 등)에서 생기고, API 로 처음 다룰 수 있는 상태.
5. verify_key_fields: 결과를 확인할 때 같은 데이터를 다시 찾는 키 필드.
6. basis: 명세에 글자로 적혀 있으면 spec, 이름 · 순서 · 일반 지식으로 추측했으면 guess. evidence 에 근거를 적는다.
7. 정렬 순서가 곧 전이 순서는 아니다. 모르는 것은 지어내지 말고 open_questions 에 적는다."""
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"{code_group['name']}({code_group['id']}) 그래프 재료를 만들어 줘."}]


def _selector(item: dict[str, Any]) -> dict[str, str]:
    return {item["selector_field"]: str(item["selector_value"])} if item.get("selector_field") else {}


def to_knowledge(out: BaseModel | dict[str, Any], code_group: dict[str, Any], domain: str,
                 source: str = "llm") -> dict[str, Any]:
    """LLM 출력 → knowledge 형식 dict (사람이 쓴 yaml 과 같은 모양 + basis · evidence).

    domain 은 그래프 담당 = 상태 코드 그룹의 주인. 동작 API 의 도메인과 다를 수 있다 (주문상태: od, API: ds).
    """
    d = out.model_dump() if isinstance(out, BaseModel) else dict(out)
    return {
        "graph": {"id": code_group["id"], "name": code_group["name"], "domain": domain, "entity": d["entity"],
                  "state_field": d.get("state_field"), "entry_states": list(d.get("entry_states") or []),
                  "verify_key_fields": list(d.get("verify_key_fields") or [])},
        "code_group": code_group,
        "transitions": [{"api": t["api_id"], "selector": _selector(t), "name": t["name"],
                         "from": t["from_code"], "to": t["to_code"], "source": source,
                         "basis": t["basis"], "evidence": t["evidence"]} for t in d["transitions"]],
        "lookups": [{"api": lk["api_id"], "selector": _selector(lk), "states": list(lk["states"]),
                     "basis": lk["basis"], "evidence": lk["evidence"]} for lk in d["lookups"]],
        "open_questions": list(d.get("open_questions") or []),
    }


def extract_knowledge(code_group: dict[str, Any], operations: list[dict[str, Any]],
                      metadata: list[dict[str, Any]], llm: LLMParse, domain: str) -> dict[str, Any]:
    schema = extract_schema(code_group["codes"], [o["api_id"] for o in operations])
    out = llm(build_messages(code_group, spec_digest(operations, metadata)), schema)
    return to_knowledge(out, code_group, domain)
