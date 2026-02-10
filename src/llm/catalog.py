from __future__ import annotations

import json
from pathlib import Path

from llm.models import ModelCatalogEntry


def load_model_catalog(path: Path | None = None) -> list[ModelCatalogEntry]:
    if path and path.exists():
        raw = json.loads(path.read_text())
        return [
            ModelCatalogEntry(
                id=item["id"],
                provider=item["provider"],
                name=item.get("name", item["id"]),
                context_window=item.get("context_window"),
                reasoning=item.get("reasoning"),
            )
            for item in raw
        ]

    return [
        ModelCatalogEntry(id="gpt-4.1-mini", provider="openai", name="GPT-4.1 mini", context_window=128000),
        ModelCatalogEntry(id="gpt-4.1", provider="openai", name="GPT-4.1", context_window=128000),
        ModelCatalogEntry(id="claude-3-5-sonnet-latest", provider="anthropic", name="Claude Sonnet", context_window=200000),
        ModelCatalogEntry(id="claude-3-7-sonnet-latest", provider="anthropic", name="Claude 3.7 Sonnet", context_window=200000),
    ]
