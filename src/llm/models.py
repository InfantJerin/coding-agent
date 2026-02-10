from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str


@dataclass(frozen=True)
class ModelCatalogEntry:
    id: str
    provider: str
    name: str
    context_window: int | None = None
    reasoning: bool | None = None
