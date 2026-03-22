from __future__ import annotations

from typing import Any

from deal_agent_platform.domain import EventResolution, NormalizedEvent, new_id, utc_now


class EventNormalizer:
    def normalize(
        self,
        *,
        source: str,
        context_id: str,
        resolution_method: str,
        resolution_confidence: float,
        raw_event: dict[str, Any],
    ) -> NormalizedEvent:
        payload = dict(raw_event.get("payload", {}))
        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        artifact_hash = (
            metadata.get("content_hash")
            or payload.get("content_hash")
            or raw_event.get("artifact_hash")
        )
        artifact_version = (
            payload.get("version")
            if isinstance(payload.get("version"), int)
            else raw_event.get("artifact_version")
        )
        return NormalizedEvent(
            event_id=str(raw_event.get("event_id") or new_id("evt")),
            context_id=context_id,
            event_type=str(raw_event.get("event_type") or "app_event"),
            source=source,
            timestamp=str(raw_event.get("timestamp") or utc_now()),
            payload=payload,
            resolution=EventResolution(
                method=resolution_method,
                confidence=resolution_confidence,
            ),
            artifact_hash=str(artifact_hash) if artifact_hash else None,
            artifact_version=artifact_version if isinstance(artifact_version, int) else None,
            lineage_parent=(
                str(payload.get("lineage_parent"))
                if payload.get("lineage_parent") is not None
                else None
            ),
        )
