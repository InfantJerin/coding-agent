from __future__ import annotations

from llm.models import ModelCatalogEntry, ModelRef


ALIASES = {
    "sonnet": ModelRef(provider="anthropic", model="claude-3-5-sonnet-latest"),
    "gpt41": ModelRef(provider="openai", model="gpt-4.1"),
    "gpt41mini": ModelRef(provider="openai", model="gpt-4.1-mini"),
}


def parse_model_ref(raw: str, default_provider: str = "openai") -> ModelRef | None:
    value = raw.strip()
    if not value:
        return None
    alias = ALIASES.get(value.lower())
    if alias:
        return alias
    if "/" not in value:
        return ModelRef(provider=default_provider, model=value)
    provider, model = value.split("/", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        return None
    return ModelRef(provider=provider, model=model)


def resolve_model_ref(catalog: list[ModelCatalogEntry], requested: str | None) -> ModelRef | None:
    if requested:
        parsed = parse_model_ref(requested)
        if not parsed:
            return None
        for entry in catalog:
            if entry.provider == parsed.provider and entry.id == parsed.model:
                return parsed
        return parsed

    return ModelRef(provider=catalog[0].provider, model=catalog[0].id) if catalog else None
