"""Tool Registry 생성 — 실행기가 실제로 부르는 도구 목록. API 하나 = 도구 하나, PK 는 api_id.

연결 설정(base URL 환경변수 · timeout · 인증 · 허용 환경)은 도메인 단위로 사람이 정하고(services.yaml),
재시도 · 승인 게이트는 쓰기/조회에 따라 고정한다 (쓰기를 재시도하면 데이터가 중복 생성된다).

값 결정 순서: 도메인 설정 > 서비스 기본값 > 명세에서 추정한 값
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tap.models import ApiOperation, ConnSettings, ToolSpec

RETRY = {"write": 0, "read": 2}
PROD_ENVS = {"PROD", "PRD", "REAL", "OPER", "OPERATION", "LIVE"}     # 정책상 항상 제외


def load_services(path: str | Path) -> list[dict[str, Any]]:
    return (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("services", [])


def service_name(spec_source: str, services: list[dict[str, Any]]) -> str:
    svc = next((s for s in services if s.get("spec") == spec_source), None)
    return svc["name"] if svc else Path(spec_source).stem


def resolve_conn(spec_source: str, domain: str, services: list[dict[str, Any]],
                 spec_base_url: str, header_keys: list[str]) -> ConnSettings:
    """한 도메인의 연결 설정을 정한다."""
    svc = next((s for s in services if s.get("spec") == spec_source), None)
    if not svc:
        return ConnSettings(service=Path(spec_source).stem, domain=domain, base_url="",
                            base_url_default=spec_base_url,
                            auth_type="API_KEY_HEADER" if header_keys else "NONE",
                            auth_headers=header_keys, source="spec")

    base = svc.get("defaults") or {}
    dom = (svc.get("domains") or {}).get(domain) or {}
    used: set[str] = set()

    def pick(key: str, default=None):
        if dom.get(key) not in (None, ""):
            used.add("domain")
            return dom[key]
        if base.get(key) not in (None, ""):
            used.add("service")
            return base[key]
        return default

    auth = pick("auth", {}) or {}
    envs = [e for e in (pick("allowed_environments", ["DEV"]) or []) if str(e).upper() not in PROD_ENVS]
    return ConnSettings(
        service=svc["name"], domain=domain,
        base_url=pick("base_url", "") or "",
        base_url_default=spec_base_url,
        timeout_ms=int(pick("timeout_ms", 5000)),
        auth_type=auth.get("type") or ("API_KEY_HEADER" if header_keys else "NONE"),
        auth_profile=auth.get("profile"),
        auth_headers=auth.get("headers") or header_keys,
        default_headers=pick("default_headers", {}) or {},
        allowed_environments=envs,
        source="domain" if "domain" in used else ("service" if "service" in used else "spec"),
    )

# ------------------------------------------------------------- 성공 판단 규칙


def infer_success_rule(op: ApiOperation) -> dict[str, str] | None:
    """성공 응답(200) 구조에서 성공 판단 규칙을 추정한다. Hmall 은 실패도 HTTP 200 이라 본문으로 본다.

    - 'code' 필드의 예시가 0000 → {path: <dataset>/code, equals: 0000}
    - 'result' 필드의 예시가 Request Success → {path: <dataset>/result, equals: Request Success}
    - 둘 다 없으면 None (검수 대상)
    """
    for name, want in (("code", "0000"), ("result", "Request Success")):
        for f in op.response_fields:
            if f.name == name and (f.example == want or (f.raw_example or "") == want):
                return {"path": f"{f.dataset_id or ''}/{f.name}".lstrip("/"), "equals": want}
    return None


def body_format(op: ApiOperation) -> str | None:
    ct = (op.request_content_type or "").lower()
    if "xml" in ct:
        return "nexacro-xml" if op.request_datasets else "xml"
    if "json" in ct:
        return "json"
    return None

# ------------------------------------------------------------------ 생성


def build_tool_registry(ops: list[ApiOperation], domains: dict[str, str], kinds: dict[str, str],
                        spec_hash: str, services: list[dict[str, Any]], spec_base_url: str,
                        overrides: dict[str, dict[str, Any]] | None = None
                        ) -> tuple[list[ConnSettings], list[ToolSpec]]:
    """(도메인별 연결 설정, 도구 목록). domains · kinds 는 api_id → 값."""
    overrides = overrides or {}
    header_keys = sorted({h.name for o in ops for h in o.headers})
    conns: dict[str, ConnSettings] = {}
    tools: list[ToolSpec] = []
    for op in ops:
        dom, kind = domains[op.api_id], kinds[op.api_id]
        conn = conns.get(dom) or resolve_conn(op.spec_source, dom, services, spec_base_url, header_keys)
        conns[dom] = conn
        ov = overrides.get(op.api_id, {})
        # 인증이 필요한데 비밀값 참조가 없으면 실행할 수 없다
        enabled = not (conn.auth_type != "NONE" and not conn.auth_profile)
        if "enabled" in ov:
            enabled = bool(ov["enabled"]) and enabled
        tools.append(ToolSpec(
            api_id=op.api_id, domain=dom, method=op.method, endpoint=op.path,
            content_type=op.request_content_type, body_format=body_format(op),
            base_url=conn.base_url, timeout_ms=conn.timeout_ms,
            retry_count=RETRY[kind], approval_required=kind == "write",
            auth_type=conn.auth_type, auth_profile=conn.auth_profile, enabled=enabled,
            default_headers=conn.default_headers,
            success_rule=ov.get("success_rule") or infer_success_rule(op),
            allowed_environments=conn.allowed_environments,
            schema_ref=None,
            source_metadata={"document_id": op.spec_source, "operation_id": op.operation_id,
                             "spec_hash": spec_hash},
        ))
    return list(conns.values()), tools
