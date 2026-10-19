"""도메인 · 쓰기/조회 분류, API Metadata · API Catalog 생성 (Catalog 는 Metadata 에서 복사).

Hmall 명세는 모든 API 가 POST 라서 HTTP 메서드로 쓰기/조회를 가를 수 없다.
operationId 의 동사(select · insert · update · multi …)와 summary 의 한국어 동사로 판별한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from tap.models import ApiCatalog, ApiCatalogEntry, ApiMetaData, ApiOperation, DomainGuess, SpecSource

# ------------------------------------------------------------------ 도메인


def load_domain_rules(path: str | Path) -> dict[str, Any]:
    """domains.yaml 을 읽어 {domains: 코드→이름, prefix: prefix→도메인, tags: 태그→도메인} 으로 펼친다.

    prefix 하나가 두 도메인에 있으면(또는 '/' 로 시작하지 않으면) 오류 — 규칙이 모호한 채로 분류하지 않는다.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    names: dict[str, str] = {}
    prefix: dict[str, str] = {}
    for code, cfg in (raw.get("domains") or {}).items():
        cfg = cfg or {}
        names[code] = cfg.get("name", code)
        for pre in cfg.get("prefixes") or []:
            pre = pre.rstrip("/") or "/"
            if not pre.startswith("/"):
                raise ValueError(f"prefix 는 '/' 로 시작해야 합니다: {code} → {pre}")
            if pre in prefix and prefix[pre] != code:
                raise ValueError(f"prefix {pre} 가 두 도메인에 있습니다: {prefix[pre]}, {code}")
            prefix[pre] = code
    tags = raw.get("tags") or {}
    for t, code in tags.items():
        if code not in names:
            raise ValueError(f"태그 {t} 가 없는 도메인 {code} 를 가리킵니다")
    return {"domains": names, "prefix": prefix, "tags": tags}


def classify_domain(op: ApiOperation, rules: dict[str, Any]) -> DomainGuess:
    for prefix, dom in sorted(rules.get("prefix", {}).items(), key=lambda kv: -len(kv[0])):
        if op.path == prefix or op.path.startswith(prefix.rstrip("/") + "/"):
            tag_dom = next((rules.get("tags", {}).get(t) for t in op.tags if t in rules.get("tags", {})), None)
            note = "" if tag_dom in (None, dom) else f" (태그 {op.tags[0]} 는 {tag_dom} — 경로 우선)"
            return DomainGuess(domain=dom, confidence="높음", reason=f"경로 {prefix}{note}")
    for t in op.tags:
        if t in rules.get("tags", {}):
            return DomainGuess(domain=rules["tags"][t], confidence="중간", reason=f"태그 {t}")
    return DomainGuess(domain="unknown", confidence="낮음", reason="경로 · 태그 규칙 없음 — 검수 필요")

# ------------------------------------------------------------- 쓰기 / 조회

# operationId 앞 동사 → (kind, action)
VERB_RULES: list[tuple[str, str, str]] = [
    ("select", "read", "조회"), ("get", "read", "조회"), ("search", "read", "조회"),
    ("list", "read", "조회"), ("inquiry", "read", "조회"),
    ("insert", "write", "등록"), ("create", "write", "등록"), ("regist", "write", "등록"),
    ("update", "write", "수정"), ("upload", "write", "수정"), ("modify", "write", "수정"),
    ("delete", "write", "삭제"), ("remove", "write", "삭제"), ("save", "write", "저장"),
    ("multi", "write", "등록·수정"),
]
# summary 한국어 동사 — 동사 규칙보다 구체적이면 덮어쓴다
SUMMARY_ACTIONS = [("처리", "처리"), ("요청", "요청"), ("취소", "취소"), ("답변", "등록·수정"),
                   ("등록", "등록"), ("수정", "수정"), ("저장", "저장"), ("조회", "조회")]


def classify_kind(op: ApiOperation) -> tuple[str, str, str]:
    """(kind, action, 근거)."""
    oid = (op.operation_id or op.path.rsplit("/", 1)[-1]).split(".")[0]
    low = oid[:1].lower() + oid[1:]
    kind = action = None
    reason = ""
    for verb, k, a in VERB_RULES:
        if low.lower().startswith(verb):
            kind, action, reason = k, a, f"operationId 동사 '{verb}'"
            break
    summ = op.summary or ""
    for word, a in SUMMARY_ACTIONS:
        if word in summ:
            if kind is None:
                kind = "read" if a == "조회" else "write"
                reason = f"summary '{word}'"
            if kind == "write" and a != "조회":
                action = a
                reason += f" · summary '{word}'"
            break
    if kind is None:                            # 판단 불가 — 안전하게 쓰기로 둔다 (재시도 0 · 승인 필요)
        return "write", "미상", "규칙 없음 — 쓰기로 간주(안전 기본값)"
    return kind, action or "미상", reason


ACTION_WORDS = ("목록", "상세", "전체", "리스트", "조회", "등록", "수정", "처리", "요청",
                "저장", "삭제", "취소", "변경", "관리", "템플릿", "답변")


def entity_hint(op: ApiOperation) -> str | None:
    """summary 에서 동작어를 걷어내 다루는 대상을 남긴다. '상품 상세 조회' → '상품'.

    낱말 단위로만 지운다 — '상품필수정보' 안의 '수정' 같은 글자는 건드리지 않는다.
    """
    s = re.sub(r"\[[^\]]*\]", " ", op.summary or "")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[,/·]", " ", s)
    kept: list[str] = []
    for tok in s.split():
        if tok in ACTION_WORDS:
            continue
        for w in ACTION_WORDS:                  # '취소조회' → '취소' (뒤에 붙은 동작어 하나만)
            if tok.endswith(w) and len(tok) > len(w):
                tok = tok[: -len(w)]
                break
        kept.append(tok)
    return " ".join(kept) or None


_STATUS_LABEL = re.compile(r"(상태|진행|단계)")
_STATUS_NAME = re.compile(r"(Stat|Status|StatGbcd|Step)$", re.I)   # 일반 '구분(Gb)' 은 제외 — 상태가 아닌 경우가 많다


def status_fields(op: ApiOperation) -> list[str]:
    """상태 전이에 쓰일 만한 요청 필드 — 이름 · 한글 이름으로 고른다 (State Graph 단서)."""
    out: list[str] = []
    for f in op.request_fields:
        if (_STATUS_LABEL.search(f.label or "") or _STATUS_NAME.search(f.name)) and f.name not in out:
            out.append(f.name)
    return out

# ------------------------------------------------------------------ 버전 · 해시


def content_hash(obj: Any) -> str:
    """내용 지문 — 키 순서와 상관없이 같은 내용이면 같은 값."""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def next_version(prev_version: int | None, prev_hash: str | None, new_hash: str) -> int:
    """내용이 같으면 그대로, 다르면 +1, 처음이면 1."""
    if prev_version is None:
        return 1
    return prev_version if prev_hash == new_hash else prev_version + 1

# --------------------------------------------------------------- 사람 보정


def load_overrides(path: str | Path) -> dict[str, dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return {}
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("apis") or {}


# 오버라이드에 적을 수 있는 키 — 여기 없는 키는 조용히 무시하지 않고 빌드를 멈춘다
OVERRIDE_KEYS = {
    "description": "설명 보정 (문자열)",
    "aliases": "별칭 추가 (문자열 목록)",
    "irreversible": "되돌림 불가 (미확인 · 가능 · 불가)",
    "memo": "구별 메모 (문자열)",
    "enabled": "사용 여부 (true/false)",
    "success_rule": "성공 판단 규칙 ({path, equals})",
}
_HINTS = {"tool_enabled": "enabled", "desc": "description", "alias": "aliases", "irreversable": "irreversible"}


class OverrideError(ValueError):
    """오버라이드 파일에 모르는 키 · 잘못된 값 · 없는 api_id 가 있다."""


def validate_overrides(overrides: dict[str, dict[str, Any]], api_ids: set[str]) -> None:
    errors: list[str] = []
    for api_id, ov in overrides.items():
        if api_id not in api_ids:
            errors.append(f"{api_id}: 명세에 없는 api_id")
        if not isinstance(ov, dict):
            errors.append(f"{api_id}: 항목이 키-값 형식이 아님")
            continue
        for key, val in ov.items():
            if key not in OVERRIDE_KEYS:
                hint = f" — '{_HINTS[key]}' 를 쓰세요" if key in _HINTS else ""
                errors.append(f"{api_id}: 모르는 키 '{key}'{hint}")
            elif key == "irreversible" and val not in ("미확인", "가능", "불가"):
                errors.append(f"{api_id}: irreversible 는 미확인 · 가능 · 불가 중 하나 (받은 값: {val!r})")
            elif key == "aliases" and not (isinstance(val, list) and all(isinstance(a, str) for a in val)):
                errors.append(f"{api_id}: aliases 는 문자열 목록")
            elif key == "enabled" and not isinstance(val, bool):
                errors.append(f"{api_id}: enabled 는 true/false")
            elif key in ("description", "memo") and val is not None and not isinstance(val, str):
                errors.append(f"{api_id}: {key} 는 문자열")
            elif key == "success_rule" and not (isinstance(val, dict) and set(val) == {"path", "equals"}):
                errors.append(f"{api_id}: success_rule 은 {{path, equals}} 두 키")
    if errors:
        allowed = ", ".join(f"{k}({v})" for k, v in OVERRIDE_KEYS.items())
        raise OverrideError("overrides.yaml 오류\n  - " + "\n  - ".join(errors) + f"\n허용 키: {allowed}")

# ------------------------------------------------------------- API Metadata


def _norm(s: str | None) -> str:
    return " ".join((s or "").split())


def auto_description(op: ApiOperation) -> str | None:
    """명세 description 이 summary 와 같으면 비운다 — 같은 말을 두 번 주지 않는다."""
    d, s = _norm(op.description), _norm(op.summary)
    return None if not d or d == s else d


def _meta_body(m: ApiMetaData) -> dict[str, Any]:
    """버전 비교용 — 버전 번호 자신은 뺀다."""
    return m.model_dump(mode="json", exclude={"metadata_version"})


def build_metadata(ops: list[ApiOperation], guesses: dict[str, DomainGuess], tools_enabled: dict[str, bool],
                   spec_hashes: dict[str, str], overrides: dict[str, dict[str, Any]],
                   previous: dict[str, dict[str, Any]] | None = None) -> tuple[list[ApiMetaData], list[dict]]:
    """(Metadata 목록, 검수 대상). previous: 지난번 api_metadata.json (api_id → 항목) — 버전 비교용."""
    previous = previous or {}
    out: list[ApiMetaData] = []
    review: list[dict] = []
    for op in ops:
        g = guesses[op.api_id]
        kind, action, why = classify_kind(op)
        ov = overrides.get(op.api_id, {})
        auto_aliases: list[str] = []                 # 1차: 자동 별칭(LLM)은 아직 없음
        aliases = list(dict.fromkeys(auto_aliases + list(ov.get("aliases") or [])))
        name = op.summary or op.operation_id or op.api_id
        desc = ov.get("description", auto_description(op))
        m = ApiMetaData(
            api_id=op.api_id, api_name=name, domain=g.domain, kind=kind, action=action,
            description=desc, aliases=aliases,
            irreversible=ov.get("irreversible", "미확인" if kind == "write" else "가능"),
            memo=ov.get("memo"),
            tool_enabled=tools_enabled.get(op.api_id, True),
            search_text=" ".join(x for x in [op.operation_id or "", name, desc or "", *aliases,
                                             ov.get("memo") or ""] if x),
            document_id=op.spec_source, operation_id=op.operation_id,
            spec_hash=spec_hashes[op.spec_source],
        )
        prev = previous.get(op.api_id)
        prev_body = {k: v for k, v in prev.items() if k != "metadata_version"} if prev else None
        m.metadata_version = next_version(prev.get("metadata_version") if prev else None,
                                          content_hash(prev_body) if prev else None, content_hash(_meta_body(m)))
        out.append(m)
        if g.confidence != "높음":
            review.append({"api_id": op.api_id, "item": "domain", "reason": g.reason})
        if action == "미상":
            review.append({"api_id": op.api_id, "item": "kind", "reason": why})
    return out, review

# -------------------------------------------------------------- API Catalog


def build_catalog(meta: list[ApiMetaData], spec_sources: list[SpecSource],
                  previous: dict[str, Any] | None = None, now: str | None = None) -> ApiCatalog:
    """Metadata 에서 Catalog 필드만 복사한다. 버전은 내용 해시가 바뀔 때만 올린다."""
    apis = [ApiCatalogEntry(api_id=m.api_id, operation_id=m.operation_id, api_name=m.api_name,
                            description=m.description, domain=m.domain, kind=m.kind,
                            aliases=m.aliases, tool_enabled=m.tool_enabled) for m in meta]
    h = content_hash({"spec_sources": [s.model_dump(mode="json") for s in spec_sources],
                      "apis": [a.model_dump(mode="json") for a in apis]})
    prev = previous or {}
    version = next_version(prev.get("catalog_version"), prev.get("catalog_hash"), h)
    return ApiCatalog(
        catalog_version=version, catalog_hash=h,
        generated_at=now or datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        spec_sources=spec_sources, apis=apis,
    )
