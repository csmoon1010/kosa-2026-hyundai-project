"""노트북 산출물의 JSON 조회 계층. SQLite/노트북 실행 없이 UI 계약을 구성한다."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def artifact_directory(root: Path) -> Path:
    return root / "data" / "out" / "parameters"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def selected_id(data: dict) -> str | None:
    document = data.get("document_id", data.get("documentId"))
    api = data.get("api_id", data.get("apiId"))
    # 구 operationId 기반 산출물은 섞지 않는다.
    if not isinstance(document, str) or not isinstance(api, str) or not re.match(r"^[A-Z]+:/", api):
        return None
    return f"{document}:{api}"


def _records(folder: Path, warnings: list[str]) -> dict:
    records = {}
    for path in sorted(folder.rglob("*.json")):
        try:
            data = _read(path)
            sid = selected_id(data) if isinstance(data, dict) else None
            if sid is None:
                continue
            if sid in records:
                raise ValueError(f"중복 API ID: {sid}")
            records[sid] = data
        except (ValueError, OSError) as error:
            warnings.append(f"{path.name}: {error}")
    return records


def _verified(items: list) -> list:
    verified = [deepcopy(k) for k in items if k.get("status") == "VERIFIED"]
    superseded = {k.get("supersedes_id") for k in verified if k.get("supersedes_id")}
    return [k for k in verified if k.get("knowledge_id") not in superseded]


def _example(parameter: dict):
    value = parameter.get("example")
    if not isinstance(value, str):
        return value
    if parameter.get("xmlAttribute") and parameter.get("name") == "id":
        return value.split("(", 1)[0].strip() or None
    match = re.search(r"\([^()]*?(?:예시|예|example)\s*:\s*([^()]*)\)\s*$", value, re.I)
    return (match.group(1).strip() if match else value.strip()) or None


def _field(parameter: dict) -> dict:
    result = deepcopy(parameter)
    result["parameter_path"] = parameter.get("parameter_path", parameter.get("path"))
    return result


def _example_baseline(canonical: dict) -> dict:
    fields = []
    for parameter in canonical["parameters"]:
        field = _field(parameter)
        value = _example(parameter)
        field.update(value=value, value_source="EXAMPLE" if value is not None else "UNRESOLVED")
        fields.append(field)
    sid = selected_id(canonical)
    return {"document_id": canonical["documentId"], "api_id": canonical["apiId"],
            "selected_api_id": sid, "content_type": canonical.get("contentType"),
            "user_registered": False, "source": "EXAMPLE", "validation_status": "EXAMPLE_ONLY",
            "parameters": fields, "baseline_xml": None}


def load_preprocessing(root: Path) -> dict:
    """원본 구조를 보존하고 승인 지식/활성 성공응답만 클라이언트에 제공한다."""
    directory, warnings = artifact_directory(root), []
    canonical = _records(directory / "canonical_schema", warnings)
    baseline_source = _records(directory / "baseline", warnings)
    kb_source = _records(directory / "parameter_kb/api", warnings)
    response_source = _records(directory / "response_outputs", warnings)
    overrides = _records(root / "data/baselines/preprocessing", warnings)
    kb, baselines, responses = {}, {}, {}
    for sid, api in canonical.items():
        api["selected_api_id"] = sid
        api["parameters"] = [_field(p) for p in api.get("parameters", [])]
        defaults = _example_baseline(api)
        baseline = deepcopy(overrides.get(sid, baseline_source.get(sid, defaults)))
        baseline["parameters"] = [_field(p) for p in baseline.get("parameters", [])]
        baseline["example_values"] = {p["parameter_path"]: p["value"] for p in defaults["parameters"]}
        baseline["selected_api_id"] = sid
        baseline["user_registered"] = baseline.get("user_registered") is True
        baselines[sid] = baseline

        source = kb_source.get(sid)
        if source:
            source = deepcopy(source)
            valid_paths = {p["parameter_path"] for p in api["parameters"]}
            source["parameters"] = [p for p in source.get("parameters", [])
                                    if p.get("provenance", {}).get("source") == "CANONICAL_DERIVED"
                                    and p.get("identity", {}).get("parameter_path") in valid_paths
                                    and selected_id(p.get("identity", {})) == sid]
            source["api_knowledge"] = [k for k in _verified(source.get("api_knowledge", []))
                                       if k.get("kb_scope") == "API"
                                       and k.get("canonical_document_id") == api["documentId"]
                                       and api["apiId"] in (k.get("api_ids") or [])]
            source["common_candidates"] = [k for k in _verified(source.get("common_candidates", []))
                                           if k.get("kb_scope") == "COMMON"]
            source["selected_api_id"] = sid
            kb[sid] = source

        source = response_source.get(sid)
        if source:
            definitions = [r for r in source.get("responses", []) if r.get("is_active") is True
                           and r.get("response_kind") == "SUCCESS" and selected_id(r) == sid
                           and r.get("extraction_status") == "COMPLETE"]
            keys = {(r["response_key"], r["content_type"]) for r in definitions}
            outputs = []
            for output in source.get("outputs", []):
                if (selected_id(output) != sid or (output.get("response_key"), output.get("content_type")) not in keys
                        or output.get("enabled") is not True or output.get("is_active") is not True
                        or output.get("review_required") is not False or output.get("response_kind") != "SUCCESS"
                        or output.get("response_is_active") is not True):
                    continue
                field = deepcopy(output)
                field["parameter_path"] = output["schema_path"]
                field["xmlPath"] = output.get("response_path") if output.get("path_type") == "XPATH" else None
                metadata = output.get("metadata", {})
                field["required"] = metadata.get("required", False)
                field["requiredDeclared"] = metadata.get("required_declared", False)
                outputs.append(field)
            responses[sid] = {"document_id": api["documentId"], "api_id": api["apiId"],
                              "selected_api_id": sid, "responses": definitions, "outputs": outputs,
                              "on_unmatched_response": "stop"}
    common_path = directory / "parameter_kb/common/knowledge.json"
    common = []
    if common_path.is_file():
        try:
            common = [k for k in _verified(_read(common_path)) if k.get("kb_scope") == "COMMON"]
        except (ValueError, OSError) as error:
            warnings.append(f"{common_path.name}: {error}")
    return {"loaded_at": datetime.now(timezone.utc).isoformat(),
            "source_directory": str(directory), "canonical_schema": canonical, "baselines": baselines,
            "parameter_kb": kb, "common_knowledge": common, "response_outputs": responses,
            "warnings": warnings, "response_policy": {"on_unmatched_success": "stop"},
            "counts": {"canonical_schema": len(canonical), "baseline": len(baselines),
                       "parameter_kb": len(kb), "response_outputs": len(responses)}}


def legacy_baselines(preprocessing: dict) -> dict:
    """기존 등록 건수/미리보기용. 예시 초안과 동명 필드를 등록값으로 취급하지 않는다."""
    result = {}
    for sid, record in preprocessing["baselines"].items():
        if not record["user_registered"]:
            continue
        fields = [p for p in record["parameters"] if p.get("location") == "body"]
        counts = Counter(p["name"] for p in fields)
        result[sid] = {"api_id": sid, "body": {p["name"]: p.get("value") for p in fields if counts[p["name"]] == 1},
                       "by": "사용자 등록", "at": record.get("registered_at", ""), "user_registered": True}
    return result


def save_preprocessing_baseline(root: Path, sid: str, values: dict) -> Path:
    data = load_preprocessing(root)
    if sid not in data["canonical_schema"]:
        raise ValueError(f"Canonical Schema가 없는 API: {sid}")
    if not isinstance(values, dict):
        raise ValueError("values는 parameter_path별 값 객체여야 합니다")
    canonical = data["canonical_schema"][sid]
    definitions = {p["parameter_path"]: p for p in canonical["parameters"]}
    extra = set(values) - definitions.keys()
    if extra:
        raise ValueError("정의되지 않은 parameter_path: " + ", ".join(sorted(extra)))
    record = deepcopy(data["baselines"][sid])
    for field in record["parameters"]:
        path = field["parameter_path"]
        if path not in values:
            continue
        value, schema = values[path], definitions[path]
        # 숫자로 보이는 문자열 코드도 문자열로 보존한다.
        if value is not None:
            kind = schema.get("type")
            valid = ((kind == "string" and isinstance(value, str))
                     or (kind == "integer" and type(value) is int)
                     or (kind == "number" and type(value) in (int, float))
                     or (kind == "boolean" and type(value) is bool)
                     or (kind == "array" and isinstance(value, list))
                     or (kind == "object" and isinstance(value, dict)))
            if not valid:
                raise ValueError(f"{path}: {kind} 타입 값이 필요합니다")
            if schema.get("enum") and value not in schema["enum"]:
                raise ValueError(f"{path}: 허용된 enum 값이 아닙니다")
        field.update(value=value, value_source="USER_REGISTERED" if value is not None else "UNRESOLVED")
    record.update(user_registered=True, source="USER_REGISTERED", baseline_xml=None,
                  validation_status="FIELD_VALUES_CHECKED", registered_at=datetime.now(timezone.utc).isoformat())
    record.pop("example_values", None)
    destination = root / "data/baselines/preprocessing" / (hashlib.sha256(sid.encode()).hexdigest()[:24] + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return destination
