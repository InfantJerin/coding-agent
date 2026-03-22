from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deal_agent_platform.application.interfaces import ContextConfigStore
from deal_agent_platform.domain import EventResolution


@dataclass
class ResolutionResult:
    context_id: str
    resolution: EventResolution


class ContextResolver:
    """Deterministic context resolver with documented tiered fallback order."""

    def __init__(self, config_store: ContextConfigStore) -> None:
        self._config_store = config_store

    def resolve(self, *, source: str, payload: dict[str, Any]) -> ResolutionResult | None:
        if payload.get("context_id"):
            return ResolutionResult(
                context_id=str(payload["context_id"]),
                resolution=EventResolution(method="explicit", confidence=1.0),
            )

        for config in self._config_store.list_all():
            mappings = config.source_mappings
            if source == "sharepoint":
                path = str(payload.get("path", ""))
                if any(path.startswith(prefix.rstrip("*")) for prefix in mappings.sharepoint_paths):
                    return ResolutionResult(
                        context_id=config.context_id,
                        resolution=EventResolution(method="path_mapping", confidence=1.0),
                    )
            elif source == "email":
                alias = str(payload.get("mailbox_alias", "")).lower()
                if alias and alias in {a.lower() for a in mappings.email_aliases}:
                    return ResolutionResult(
                        context_id=config.context_id,
                        resolution=EventResolution(method="alias_mapping", confidence=1.0),
                    )
            elif source == "lockbox":
                account = str(payload.get("account_id", ""))
                if account and account in set(mappings.lockbox_accounts):
                    return ResolutionResult(
                        context_id=config.context_id,
                        resolution=EventResolution(method="path_mapping", confidence=1.0),
                    )
            elif source == "clearpar":
                trade_id = str(payload.get("trade_id", ""))
                if trade_id and trade_id in set(mappings.clearpar_trade_ids):
                    return ResolutionResult(
                        context_id=config.context_id,
                        resolution=EventResolution(method="path_mapping", confidence=1.0),
                    )
            elif source == "bql":
                bql_context = str(payload.get("context_id", ""))
                if bql_context == config.context_id:
                    return ResolutionResult(
                        context_id=config.context_id,
                        resolution=EventResolution(method="bql_tagged", confidence=1.0),
                    )
        return None
