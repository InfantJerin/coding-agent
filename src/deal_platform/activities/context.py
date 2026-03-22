from __future__ import annotations

from typing import Any

from temporalio import activity

from deal_platform.context_registry.storage import LocalContextStore

_store = LocalContextStore()


@activity.defn
async def load_context_config(context_id: str) -> dict[str, Any]:
    """Load and return context.yaml as a dict."""
    config = _store.load_config(context_id)
    if config is None:
        raise FileNotFoundError(f"No context.yaml found for {context_id}")
    return config
