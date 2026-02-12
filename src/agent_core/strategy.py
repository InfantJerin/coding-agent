from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RunStrategy:
    name: str
    parse_strategy: str
    run_steps: list[str]


_DEFAULT_STRATEGY_PATH = Path(__file__).resolve().parent / "document_strategies.yaml"


def _read_strategy_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Strategy file must contain a YAML object: {path}")
    return payload


def _normalize_strategy(name: str, row: dict[str, Any]) -> RunStrategy:
    parse_strategy = str(row.get("parse_strategy", "legal_contract")).strip() or "legal_contract"
    run_steps = row.get("run_steps", ["bootstrap", "extract", "qa", "report"])
    if not isinstance(run_steps, list) or not all(isinstance(item, str) for item in run_steps):
        raise ValueError(f"Invalid run_steps for strategy '{name}'")
    return RunStrategy(name=name, parse_strategy=parse_strategy, run_steps=run_steps)


def resolve_run_strategy(document_type: str, metadata: dict[str, Any] | None = None) -> RunStrategy:
    metadata = metadata or {}
    strategy_path = metadata.get("strategy_path")
    if strategy_path:
        path = Path(str(strategy_path)).expanduser().resolve()
    else:
        path = _DEFAULT_STRATEGY_PATH

    if not path.exists():
        return RunStrategy(name="fallback", parse_strategy="legal_contract", run_steps=["bootstrap", "extract", "qa", "report"])

    payload = _read_strategy_yaml(path)
    default_row = payload.get("default", {"parse_strategy": "legal_contract", "run_steps": ["bootstrap", "extract", "qa", "report"]})
    by_doc = payload.get("document_types", {})
    selected = default_row
    if isinstance(by_doc, dict) and isinstance(by_doc.get(document_type), dict):
        selected = by_doc[document_type]

    # Optional per-run inline override
    inline = metadata.get("strategy_override")
    if isinstance(inline, dict):
        selected = {**selected, **inline}

    return _normalize_strategy(name=str(document_type), row=selected if isinstance(selected, dict) else default_row)
