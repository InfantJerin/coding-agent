from __future__ import annotations

from typing import Any

from deal_agent_platform.application.interfaces import WorkflowSignalDispatcher
from deal_agent_platform.channel_bridge.normalizer import EventNormalizer
from deal_agent_platform.channel_bridge.resolver import ContextResolver
from deal_agent_platform.domain import NormalizedEvent


class ChannelBridgeService:
    """Receives raw channel events and emits normalized workflow signals."""

    def __init__(
        self,
        *,
        resolver: ContextResolver,
        normalizer: EventNormalizer,
        dispatcher: WorkflowSignalDispatcher,
    ) -> None:
        self._resolver = resolver
        self._normalizer = normalizer
        self._dispatcher = dispatcher

    def ingest(self, raw_event: dict[str, Any]) -> NormalizedEvent:
        source = str(raw_event.get("source") or "api")
        payload = raw_event.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("raw_event.payload must be a dictionary")

        result = self._resolver.resolve(source=source, payload=payload)
        if result is None:
            raise LookupError(f"Could not resolve context for source={source}")

        normalized = self._normalizer.normalize(
            source=source,
            context_id=result.context_id,
            resolution_method=result.resolution.method,
            resolution_confidence=result.resolution.confidence,
            raw_event=raw_event,
        )
        self._dispatcher.dispatch_event(normalized)
        return normalized
