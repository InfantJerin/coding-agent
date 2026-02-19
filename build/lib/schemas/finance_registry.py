from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_SCHEMA_DIR = Path(__file__).resolve().parent / "finance"
_DEFAULT_DOC_TYPE = "credit_agreement"


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Schema file must contain a YAML object: {path}")
    return payload


def _normalize_schema_payload(payload: dict[str, Any], *, document_type_hint: str | None) -> tuple[str, dict[str, Any]]:
    schema = payload.get("schema", payload)
    if not isinstance(schema, dict):
        raise ValueError("Schema payload must be an object")

    fields = schema.get("fields")
    if not isinstance(fields, list):
        raise ValueError("Schema must include a 'fields' list")

    document_type = str(payload.get("document_type") or document_type_hint or _DEFAULT_DOC_TYPE).strip()
    schema.setdefault("version", "v1")
    schema.setdefault("validations", [])
    return document_type, schema


def _builtin_schema_path(document_type: str) -> Path:
    return _SCHEMA_DIR / f"{document_type}.yaml"


def list_document_types() -> list[str]:
    if not _SCHEMA_DIR.exists():
        return []
    return sorted(path.stem for path in _SCHEMA_DIR.glob("*.yaml"))


def resolve_schema(document_type: str | None = None, schema_path: str | None = None) -> tuple[str, dict[str, Any]]:
    if schema_path:
        path = Path(schema_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {path}")
        payload = _read_yaml(path)
        hint = document_type or path.stem
        return _normalize_schema_payload(payload, document_type_hint=hint)

    resolved_doc_type = (document_type or _DEFAULT_DOC_TYPE).strip() or _DEFAULT_DOC_TYPE
    candidate = _builtin_schema_path(resolved_doc_type)
    if not candidate.exists():
        candidate = _builtin_schema_path(_DEFAULT_DOC_TYPE)
    payload = _read_yaml(candidate)
    return _normalize_schema_payload(payload, document_type_hint=resolved_doc_type)

