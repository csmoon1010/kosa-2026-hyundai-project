"""OpenAPI(3.x / Swagger 2.0) YAML · JSON 을 읽어 ApiOperation 목록으로 정규화한다.

Hmall 명세의 특징
- 모든 API 가 POST, 본문은 XML 이고 구조는 Dataset → rows → row → 컬럼 (Nexacro 형식)
- 필드 설명이 description 이 아니라 example 에 '한글명(타입:string, 예:P1)' 형태로 들어 있다
  (오타 · 변형이 섞여 있다: '(예:값)', '예Y:' …)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

import yaml

from tap.models import ApiField, ApiHeader, ApiOperation

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def load_spec(path: str | Path) -> dict[str, Any]:
    """JSON · YAML 명세를 읽는다. BOM 이 붙은 파일도 받는다."""
    text = Path(path).read_text(encoding="utf-8-sig")
    if str(path).lower().endswith((".yaml", ".yml")):
        return yaml.safe_load(text)
    return json.loads(text)


# ------------------------------------------------------------------- $ref 해석

class RefResolver:
    def __init__(self, spec: dict[str, Any]):
        self.spec = spec

    def get(self, ref: str) -> dict[str, Any]:
        if not ref.startswith("#/"):
            raise ValueError(f"외부 $ref 는 지원하지 않습니다: {ref}")
        node: Any = self.spec
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def deref(self, schema: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """$ref 를 끝까지 따라간다. (스키마, 마지막 ref 이름)"""
        name = None
        seen = set()
        while isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"]
            if ref in seen:
                raise ValueError(f"순환 $ref: {ref}")
            seen.add(ref)
            name = ref.rsplit("/", 1)[-1]
            schema = self.get(ref)
        return schema, name


# ------------------------------------------------------------- example 해석

_PAREN = re.compile(r"^(?P<label>[^()]*?)\s*\((?P<inner>.*)\)\s*$", re.S)
_TYPE = re.compile(r"타입\s*:\s*(?P<t>[^,)]+)")
_EX = re.compile(r"예\s*(?P<pre>[^:,]*?)\s*:\s*(?P<v>.*)$", re.S)


def parse_example(raw: Any) -> tuple[str | None, str | None, str | None]:
    """'진행구분코드(타입:string, 예:P1)' → ('진행구분코드', 'string', 'P1').

    형식이 아니면 (None, None, 원문) 을 돌려준다.
    '예Y:' 처럼 콜론 앞에 값이 붙은 오타는 콜론 뒤가 비었을 때 앞의 값을 쓴다.
    """
    if raw is None:
        return None, None, None
    s = str(raw).strip()
    m = _PAREN.match(s)
    if not m:
        return None, None, s
    label = m.group("label").strip() or None
    if label and label.isdigit():               # 명세 오류: 한글 이름 자리에 예시 값이 들어간 경우
        label = None
    inner = m.group("inner")
    t = _TYPE.search(inner)
    e = _EX.search(inner)
    if not t and not e:                         # 괄호는 있지만 형식이 아님
        return None, None, s
    ex = None
    if e:
        ex = e.group("v").strip() or e.group("pre").strip() or None
    return label, (t.group("t").strip() if t else None), ex


# ------------------------------------------------------------- 본문 필드 펼치기

_DS_NOTE = re.compile(r"^(?P<id>[^(\s]+)\s*\((?P<note>.*)\)\s*$")


def split_dataset_id(raw: str | None) -> tuple[str | None, str | None]:
    """'dsItemHdmallImgUrl(백화점 상품 등록시에만 입력)' → ('dsItemHdmallImgUrl', '백화점 상품 등록시에만 입력')."""
    if not raw:
        return raw, None
    m = _DS_NOTE.match(raw.strip())
    return (m.group("id"), m.group("note").strip()) if m else (raw.strip(), None)


def _raw_dataset_ids(schema: dict[str, Any], resolver: "RefResolver", stack: tuple[str, ...] = ()) -> list[str]:
    """메모가 붙은 원래 Dataset 이름까지 모은다."""
    out: list[str] = []
    schema, ref_name = resolver.deref(schema)
    if ref_name and ref_name in stack:
        return out
    stack = stack + ((ref_name,) if ref_name else ())
    if schema.get("type") == "array" or "items" in schema:
        return _raw_dataset_ids(schema.get("items", {}), resolver, stack)
    props = schema.get("properties", {})
    if (schema.get("xml") or {}).get("name") == "Dataset" and "id" in props:
        id_schema, _ = resolver.deref(props["id"])
        out.append(str(props["id"].get("example", id_schema.get("example", "")) or ""))
    for key, sub in props.items():
        if key == "id":
            continue
        out.extend(_raw_dataset_ids(sub, resolver, stack))
    return out


def _is_container(schema: dict[str, Any]) -> bool:
    return schema.get("type") in ("object", "array") or "properties" in schema or "items" in schema


def iter_fields(schema: dict[str, Any], resolver: RefResolver, path: str = "",
                dataset_id: str | None = None, required: set[str] | None = None,
                stack: tuple[str, ...] = ()) -> Iterator[ApiField]:
    """스키마를 내려가며 말단 필드를 꺼낸다. Dataset 의 id 속성은 필드가 아니라 dataset_id 로 쓴다."""
    schema, ref_name = resolver.deref(schema)
    if ref_name and ref_name in stack:          # 자기 참조 방지
        return
    stack = stack + ((ref_name,) if ref_name else ())

    if schema.get("type") == "array" or "items" in schema:
        yield from iter_fields(schema.get("items", {}), resolver, path, dataset_id, None, stack)
        return

    props: dict[str, Any] = schema.get("properties", {})
    req = set(schema.get("required", []))
    xml_name = (schema.get("xml") or {}).get("name")

    # Dataset 노드: id 속성의 example 이 데이터셋 이름 (dsInput, dsCond …)
    if xml_name == "Dataset" and "id" in props:
        id_schema, _ = resolver.deref(props["id"])
        dataset_id = str(props["id"].get("example", id_schema.get("example", "")) or "") or dataset_id
        dataset_id, _ = split_dataset_id(dataset_id)

    for key, sub in props.items():
        sub_resolved, _ = resolver.deref(sub)
        sub_xml = {**(sub_resolved.get("xml") or {}), **(sub.get("xml") or {})}
        if key == "id" and sub_xml.get("attribute"):
            continue                                # Dataset id — 위에서 처리
        child_path = f"{path}/{key}" if path else key
        if _is_container(sub_resolved):
            # 하위 노드가 Dataset 이면 그 안에서 dataset_id 가 다시 정해진다
            yield from iter_fields(sub, resolver, child_path, dataset_id, None, stack)
            continue
        raw = sub.get("example", sub_resolved.get("example"))
        label, typ, ex = parse_example(raw)
        yield ApiField(
            name=key, path=child_path, dataset_id=dataset_id,
            label=label or sub.get("description") or sub_resolved.get("description"),
            type=typ or sub_resolved.get("type"),
            example=ex, required=key in req, raw_example=None if raw is None else str(raw),
        )


def _body_schema(container: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    content = (container or {}).get("content") or {}
    for ct, v in content.items():
        if "schema" in v:
            return ct, v["schema"]
    return None, None


def _datasets(schema: dict[str, Any] | None, resolver: RefResolver) -> list[str]:
    ids: list[str] = []
    if not schema:
        return ids
    for f in iter_fields(schema, resolver):
        if f.dataset_id and f.dataset_id not in ids:
            ids.append(f.dataset_id)
    return ids


# ------------------------------------------------------------------ operation

def make_api_id(service: str, method: str, path: str) -> str:
    """서비스 + 메서드 + 경로 — 'hshop-openapi:POST:/pd/pdb/multiItem.do'.

    한 서비스 안에서 메서드 + 경로 조합은 OpenAPI 구조상 하나뿐이고, 서비스를 붙여 전체에서 고유하다.
    operationId 는 명세 파일 하나 안에서만 고유하므로 키로 쓰지 않는다.
    """
    return f"{service}:{method.upper()}:{path}"


class DuplicateApiId(ValueError):
    """같은 api_id 가 두 번 나왔다 — 이름을 바꿔 덮지 않고 빌드를 멈춘다."""


def parse_operations(spec: dict[str, Any], spec_source: str, service: str | None = None) -> list[ApiOperation]:
    """spec_source: 명세 파일 이름(document_id). service: 서비스 이름 — 없으면 파일 이름에서 만든다."""
    service = service or Path(spec_source).stem
    resolver = RefResolver(spec)
    ops: list[ApiOperation] = []
    seen: set[str] = set()
    for path, item in (spec.get("paths") or {}).items():
        common_params = item.get("parameters", [])
        for method, op in item.items():
            if method not in HTTP_METHODS:
                continue
            params = [resolver.deref(p)[0] for p in common_params + op.get("parameters", [])]
            headers = [ApiHeader(name=p["name"], required=bool(p.get("required")),
                                 description=p.get("description"))
                       for p in params if p.get("in") == "header"]

            req_ct, req_schema = _body_schema(op.get("requestBody"))
            if req_schema is None:              # Swagger 2.0: in: body 파라미터
                body = next((p for p in params if p.get("in") == "body"), None)
                req_schema = body.get("schema") if body else None
                req_ct = (op.get("consumes") or spec.get("consumes") or [None])[0]

            ok = (op.get("responses") or {}).get("200") or {}
            _, res_schema = _body_schema(ok)
            if res_schema is None and "schema" in ok:   # Swagger 2.0
                res_schema = ok["schema"]

            api_id = make_api_id(service, method, path)
            if api_id in seen:
                raise DuplicateApiId(f"api_id 중복: {api_id}")
            seen.add(api_id)

            notes = {}
            for raw in (_raw_dataset_ids(req_schema, resolver) if req_schema else []):
                ds, note = split_dataset_id(raw)
                if ds and note:
                    notes[ds] = note

            ops.append(ApiOperation(
                api_id=api_id, method=method.upper(), path=path,
                operation_id=op.get("operationId"),
                summary=op.get("summary"), description=op.get("description"),
                tags=op.get("tags", []), request_content_type=req_ct, headers=headers,
                request_datasets=_datasets(req_schema, resolver), dataset_notes=notes,
                request_fields=list(iter_fields(req_schema, resolver)) if req_schema else [],
                response_fields=list(iter_fields(res_schema, resolver)) if res_schema else [],
                spec_source=spec_source, service=service,
            ))
    return ops


def base_url(spec: dict[str, Any]) -> str:
    """OpenAPI 3 servers[0].url, Swagger 2.0 schemes + host + basePath."""
    servers = spec.get("servers") or []
    if servers and servers[0].get("url"):
        return servers[0]["url"].rstrip("/")
    host = spec.get("host") or ""
    if host:
        scheme = (spec.get("schemes") or ["https"])[0]
        return f"{scheme}://{host}{spec.get('basePath') or ''}".rstrip("/")
    return ""
