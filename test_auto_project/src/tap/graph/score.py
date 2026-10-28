"""그래프 재료 채점 — 정답지(사람이 확인한 knowledge) 대비 추출 결과가 얼마나 맞는지.

비교 단위
  전이      (API, 선택값) 이 같으면 같은 동작 → 전제 · 결과 상태까지 같으면 정확
  조회 방법 (API, 선택값) 이 같으면 같은 조회 → 나오는 상태 집합이 같으면 정확
            (코드 목록에 없는 상태는 추출 쪽이 고를 수 없으므로 비교에서 뺀다 — 예: 56)
  그래프    state_field · entry_states · verify_key_fields
  경로      같은 목표로 경로를 계산했을 때 정답 그래프와 같은 호출 순서가 나오는지
"""
from __future__ import annotations

from typing import Any

from tap.graph.build import graph_from_dict
from tap.graph.plan import Goal, PlanResult, plan


def _key(item: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return item["api"], tuple(sorted((k, str(v)) for k, v in (item.get("selector") or {}).items()))


def _label(key) -> str:
    api, sel = key
    return api.rsplit("/", 1)[-1] + (" " + ",".join(f"{k}={v}" for k, v in sel) if sel else "")


def _compare(gold: list[dict], got: list[dict], value) -> list[dict[str, Any]]:
    gold_by, got_by = {_key(i): i for i in gold}, {_key(i): i for i in got}
    rows = []
    for k, g in gold_by.items():
        x = got_by.get(k)
        status = "없음" if x is None else ("정확" if value(x) == value(g) else "틀림")
        rows.append({"item": _label(k), "status": status, "gold": value(g), "got": value(x) if x else None,
                     "gold_name": g.get("name"), "got_name": x.get("name") if x else None,
                     "basis": x.get("basis") if x else None, "evidence": x.get("evidence") if x else None})
    for k, x in got_by.items():
        if k not in gold_by:
            rows.append({"item": _label(k), "status": "추가", "gold": None, "got": value(x),
                         "gold_name": None, "got_name": x.get("name"), "basis": x.get("basis"),
                         "evidence": x.get("evidence")})
    return rows


def _path_sig(r: PlanResult, which: str) -> str:
    p = r.primary if which == "A" else r.alternative
    if r.status != "ok":
        return "거절"
    if p is None:
        return "없음"
    calls = " → ".join(_label((e.api_id, tuple(sorted(e.selector.items())))).split(" ", 1)[-1] for e in p.edges)
    sel = ",".join(f"{k}={v}" for k, v in sorted(p.lookup.selector.items())) or "선택값 없음"
    return f"{p.start} 조회({sel})" + (f" → {calls}" if calls else "")


def score(gold: dict[str, Any], got: dict[str, Any], goals: list[Goal] | None = None) -> dict[str, Any]:
    codes = set(str(c) for c in gold["code_group"]["codes"])
    transitions = _compare(gold.get("transitions") or [], got.get("transitions") or [],
                           lambda t: f"{t['from']}→{t['to']}")
    lookups = _compare(gold.get("lookups") or [], got.get("lookups") or [],
                       lambda lk: sorted(str(s) for s in lk["states"] if str(s) in codes))

    g, x = gold["graph"], got["graph"]
    fields = [{"item": f, "gold": g.get(f), "got": x.get(f),
               "status": "정확" if (set(map(str, g.get(f) or [])) == set(map(str, x.get(f) or []))
                                  if isinstance(g.get(f), list) else g.get(f) == x.get(f)) else "틀림"}
              for f in ("state_field", "entry_states", "verify_key_fields")]

    paths = []
    if goals:
        gg, xg = graph_from_dict(gold), graph_from_dict(got)
        for goal in goals:
            a, b = plan(gg, goal), plan(xg, goal)
            row = {"goal": f"{goal.target}" + (f" (거쳐야 함 {','.join(goal.must_pass)})" if goal.must_pass else "")}
            for w in ("A", "B"):
                row[f"gold_{w}"], row[f"got_{w}"] = _path_sig(a, w), _path_sig(b, w)
            for w in ("A", "B"):
                row[f"status_{w}"] = "같음" if row[f"gold_{w}"] == row[f"got_{w}"] else "다름"
            paths.append(row)

    def count(rows):
        return {"정답": sum(r["status"] != "추가" for r in rows), "정확": sum(r["status"] == "정확" for r in rows),
                "틀림": sum(r["status"] == "틀림" for r in rows), "없음": sum(r["status"] == "없음" for r in rows),
                "추가": sum(r["status"] == "추가" for r in rows)}

    return {"summary": {"transitions": count(transitions), "lookups": count(lookups),
                        "fields": sum(f["status"] == "정확" for f in fields),
                        "paths": {w: sum(p[f"status_{w}"] == "같음" for p in paths) for w in ("A", "B")}
                        if paths else None},
            "transitions": transitions, "lookups": lookups, "fields": fields, "paths": paths,
            "open_questions": got.get("open_questions") or []}
