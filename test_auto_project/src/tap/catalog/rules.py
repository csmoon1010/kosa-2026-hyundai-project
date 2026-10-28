"""화면(관리자 › 규칙 입력)에서 넣은 규칙 — data/config/rules.ui.yaml 한 곳에 쌓는다.

사람이 손으로 고치는 overrides.yaml 은 주석까지 그대로 두고, 화면 규칙 중 API Catalog · API MetaData 항목만
빌드할 때 overrides 로 바꿔 그 위에 합친다 (같은 키는 화면이 나중이라 이긴다, 별칭 · 구분값은 쌓인다).
State Vocabulary 동의어는 시나리오 생성 때 목표 추출(LLM)에 쓰인다. Parameter KB 항목은 저장만 한다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# 화면 항목 → overrides 키
ITEM_KEY = {("cat", "desc"): "description", ("cat", "kw"): "aliases", ("cat", "excl"): "enabled",
            ("meta", "irrev"): "irreversible", ("meta", "memo"): "memo", ("meta", "sel"): "selectors"}
IRREV = ("불가", "가능", "미확인")


class RuleError(ValueError):
    pass


def load_rules(path: str | Path | None) -> list[dict[str, Any]]:
    p = Path(path) if path else None
    if not p or not p.exists():
        return []
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("rules") or []


def save_rules(path: str | Path, rules: list[dict[str, Any]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("# 관리자 › 규칙 입력에서 저장한 규칙 (화면이 쓰는 파일 — 손으로 고치지 말고 화면에서 지운다)\n"
                          + yaml.safe_dump({"rules": rules}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def parse_selector(body: str) -> dict[str, Any]:
    """'procGb: PB2 출고완료취소 · PB3 배송완료취소 (일부)' → {field, complete, values}."""
    m = re.match(r"^\s*([A-Za-z_][\w]*)\s*:\s*(.+)$", body or "")
    if not m:
        raise RuleError("구분값은 '필드: 값 이름 · 값 이름' 형식 (예: procGb: PB2 출고완료취소 · PB3 배송완료취소)")
    rest, complete = m.group(2).strip(), True
    if rest.endswith("(일부)"):
        rest, complete = rest[: -len("(일부)")].strip(), False
    values = []
    for part in re.split(r"\s*[·,]\s*", rest):
        if not part:
            continue
        v, _, name = part.partition(" ")
        values.append({"value": v.strip(), **({"name": name.strip()} if name.strip() else {})})
    if not values:
        raise RuleError("구분값이 하나도 없습니다")
    return {"field": m.group(1), "complete": complete, "values": values}


def synonyms_of(rules: list[dict[str, Any]], graph_id: str) -> dict[str, list[str]]:
    """State Vocabulary 동의어 — 대상 '그래프ID:코드', 내용은 쉼표 · 가운뎃점으로 여러 개."""
    out: dict[str, list[str]] = {}
    for r in rules:
        if (r.get("doc"), r.get("item")) != ("sv", "syn"):
            continue
        gid, _, code = str(r.get("target") or "").partition(":")
        if gid != graph_id or not code:
            continue
        words = [w.strip() for w in re.split(r"[,·]", str(r.get("body") or "")) if w.strip()]
        out[code] = list(dict.fromkeys(out.get(code, []) + words))
    return out


def rule_overrides(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """화면 규칙 중 Catalog · MetaData 항목 → overrides 형식."""
    out: dict[str, dict[str, Any]] = {}
    for r in rules:
        key = ITEM_KEY.get((r.get("doc"), r.get("item")))
        if not key:
            continue
        ov, body = out.setdefault(r["target"], {}), str(r.get("body") or "").strip()
        if key == "aliases":
            ov["aliases"] = list(dict.fromkeys((ov.get("aliases") or []) + [a.strip() for a in re.split(r"[,·]", body) if a.strip()]))
        elif key == "enabled":
            ov["enabled"] = False
        elif key == "irreversible":
            ov["irreversible"] = body.split()[0] if body else body
        elif key == "selectors":
            ov["selectors"] = (ov.get("selectors") or []) + [parse_selector(body)]
        else:
            ov[key] = body
    return out


def merge_overrides(base: dict[str, dict[str, Any]], extra: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {k: dict(v) for k, v in base.items()}
    for api, ov in extra.items():
        cur = out.setdefault(api, {})
        for k, v in ov.items():
            if k == "aliases":
                cur[k] = list(dict.fromkeys((cur.get(k) or []) + v))
            elif k == "selectors":
                cur[k] = (cur.get(k) or []) + v
            else:
                cur[k] = v
    return out


def check_rule(rule: dict[str, Any]) -> None:
    """저장 전 형식 검사 — 통과 못 하면 RuleError (화면에 그대로 보인다)."""
    for k in ("doc", "item", "target", "body"):
        if not str(rule.get(k) or "").strip():
            raise RuleError(f"{k} 가 비어 있습니다")
    if (rule["doc"], rule["item"]) == ("meta", "irrev") and str(rule["body"]).split()[0] not in IRREV:
        raise RuleError("되돌림 불가는 '불가 · 가능 · 미확인' 중 하나로 시작해야 합니다 (예: 불가 외부 물류사로 전송)")
    if (rule["doc"], rule["item"]) == ("meta", "sel"):
        parse_selector(rule["body"])


def add_rule(rules: list[dict[str, Any]], rule: dict[str, Any], by: str = "화면") -> list[dict[str, Any]]:
    """같은 자리(place · doc · item · dom · target)의 규칙은 새 것으로 바꾼다. 별칭 · 구분값 · 값 해석은 따로 쌓는다."""
    check_rule(rule)
    keep_many = (rule["doc"], rule["item"]) in {("cat", "kw"), ("meta", "sel"), ("sv", "syn"), ("pkb", "value"), ("pkb", "def"), ("pkb", "cond")}
    same = lambda r: all(r.get(k) == rule.get(k) for k in ("place", "doc", "item", "dom", "target"))
    out = [r for r in rules if keep_many or not same(r)]
    nid = max([int(r.get("id", 0)) for r in rules] + [0]) + 1
    out.append({"id": nid, **{k: rule.get(k) for k in ("place", "doc", "item", "dom", "target", "body")},
                "by": by, "at": datetime.now().strftime("%m-%d %H:%M")})
    return out
