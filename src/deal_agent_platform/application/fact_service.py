from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deal_agent_platform.application.interfaces import FactLedger
from deal_agent_platform.domain import (
    ContextConfig,
    FactLifecycle,
    FactProvenance,
    FactRecord,
    FieldConflict,
    NormalizedEvent,
    WorkingContextState,
    new_id,
    parse_utc,
    utc_now,
)


@dataclass
class IngestionOutcome:
    skipped: bool
    reason: str
    ingested_facts: list[FactRecord]


class FactIngestionService:
    """Writes event-derived facts into the fact ledger and working state."""

    def __init__(self, ledger: FactLedger) -> None:
        self._ledger = ledger

    def ingest_event(
        self,
        *,
        config: ContextConfig,
        working_state: WorkingContextState,
        event: NormalizedEvent,
    ) -> IngestionOutcome:
        if event.event_id in working_state.seen_event_ids:
            return IngestionOutcome(skipped=True, reason="duplicate_event", ingested_facts=[])

        working_state.seen_event_ids.add(event.event_id)
        if event.artifact_hash:
            if (
                event.artifact_hash in working_state.seen_artifact_hashes
                and event.lineage_parent is None
            ):
                return IngestionOutcome(
                    skipped=True,
                    reason="duplicate_artifact_hash",
                    ingested_facts=[],
                )
            working_state.seen_artifact_hashes.add(event.artifact_hash)
            if event.lineage_parent:
                working_state.document_lineage[event.artifact_hash] = event.lineage_parent

        raw_facts = self._extract_fact_payload(event.payload)
        if not raw_facts:
            working_state.last_activity_at = utc_now()
            return IngestionOutcome(skipped=False, reason="no_facts", ingested_facts=[])

        created: list[FactRecord] = []
        for field_name, fact_info in raw_facts.items():
            fact = self._create_fact(
                context_id=event.context_id,
                event=event,
                field_name=field_name,
                value=fact_info["value"],
                confidence=fact_info["confidence"],
            )
            self._ledger.append(fact)
            created.append(fact)
            self._merge_fact(config=config, working_state=working_state, incoming=fact)

        working_state.last_activity_at = utc_now()
        return IngestionOutcome(skipped=False, reason="ok", ingested_facts=created)

    def _extract_fact_payload(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        payload_facts = payload.get("facts")
        if payload_facts is None:
            payload_facts = payload.get("extracted_terms", {})
        result: dict[str, dict[str, Any]] = {}
        for key, value in payload_facts.items():
            if isinstance(value, dict) and "value" in value:
                result[key] = {
                    "value": value.get("value"),
                    "confidence": float(value.get("confidence", 0.9)),
                }
            else:
                result[key] = {"value": value, "confidence": 0.9}
        return result

    def _create_fact(
        self,
        *,
        context_id: str,
        event: NormalizedEvent,
        field_name: str,
        value: Any,
        confidence: float,
    ) -> FactRecord:
        artifact_id = str(event.payload.get("document_ref") or event.payload.get("artifact_id") or event.event_id)
        provenance = FactProvenance(
            source=event.source,
            artifact_id=artifact_id,
            artifact_version=event.artifact_version,
            observed_at=event.timestamp,
            confidence=confidence,
        )
        return FactRecord(
            fact_id=new_id("fact"),
            context_id=context_id,
            field=field_name,
            value=value,
            lifecycle=FactLifecycle.CANDIDATE,
            provenance=provenance,
            created_at=utc_now(),
        )

    def _merge_fact(
        self,
        *,
        config: ContextConfig,
        working_state: WorkingContextState,
        incoming: FactRecord,
    ) -> None:
        current_id = working_state.candidate_fact_by_field.get(incoming.field)
        if current_id is None:
            incoming.lifecycle = FactLifecycle.CANDIDATE
            working_state.candidate_fact_by_field[incoming.field] = incoming.fact_id
            working_state.conflicts.pop(incoming.field, None)
            return

        current = self._ledger.get(incoming.context_id, current_id)
        if current is None:
            working_state.candidate_fact_by_field[incoming.field] = incoming.fact_id
            return

        if current.value == incoming.value:
            winner = self._resolve_winner(config=config, current=current, incoming=incoming)
            if winner == incoming.fact_id:
                current.lifecycle = FactLifecycle.SUPERSEDED
                current.status_reason = "same_value_replaced_by_higher_priority_source"
                incoming.lifecycle = FactLifecycle.CANDIDATE
                incoming.supersedes = current.fact_id
                working_state.candidate_fact_by_field[incoming.field] = incoming.fact_id
            else:
                incoming.lifecycle = FactLifecycle.SUPERSEDED
                incoming.status_reason = "same_value_lower_priority_source"
            return

        winner = self._resolve_winner(config=config, current=current, incoming=incoming)
        if winner is None:
            current.lifecycle = FactLifecycle.CONFLICTED
            incoming.lifecycle = FactLifecycle.CONFLICTED
            current.status_reason = "conflict_with_new_fact"
            incoming.status_reason = "conflict_with_existing_fact"
            working_state.candidate_fact_by_field.pop(incoming.field, None)
            working_state.conflicts[incoming.field] = FieldConflict(
                field=incoming.field,
                active_fact_ids=sorted({current.fact_id, incoming.fact_id}),
                reason="source/version tie with differing values",
            )
            return

        if winner == incoming.fact_id:
            incoming.lifecycle = FactLifecycle.CANDIDATE
            incoming.supersedes = current.fact_id
            current.lifecycle = FactLifecycle.SUPERSEDED
            current.status_reason = "replaced_by_higher_priority_fact"
            working_state.candidate_fact_by_field[incoming.field] = incoming.fact_id
        else:
            incoming.lifecycle = FactLifecycle.SUPERSEDED
            incoming.status_reason = "rejected_by_conflict_resolution"
        working_state.conflicts.pop(incoming.field, None)

    def _resolve_winner(
        self,
        *,
        config: ContextConfig,
        current: FactRecord,
        incoming: FactRecord,
    ) -> str | None:
        current_rank = config.get_source_priority(current.provenance.source)
        incoming_rank = config.get_source_priority(incoming.provenance.source)
        if current_rank != incoming_rank:
            return incoming.fact_id if incoming_rank < current_rank else current.fact_id

        c_ver = current.provenance.artifact_version
        i_ver = incoming.provenance.artifact_version
        if c_ver is not None and i_ver is not None and c_ver != i_ver:
            return incoming.fact_id if i_ver > c_ver else current.fact_id
        if c_ver is None and i_ver is not None:
            return incoming.fact_id
        if c_ver is not None and i_ver is None:
            return current.fact_id

        c_time = parse_utc(current.provenance.observed_at)
        i_time = parse_utc(incoming.provenance.observed_at)
        if c_time != i_time:
            return incoming.fact_id if i_time > c_time else current.fact_id

        c_conf = current.provenance.confidence
        i_conf = incoming.provenance.confidence
        if c_conf != i_conf:
            return incoming.fact_id if i_conf > c_conf else current.fact_id

        # Explicit tie means unresolved conflict if values differ.
        if current.value != incoming.value:
            return None
        return current.fact_id
