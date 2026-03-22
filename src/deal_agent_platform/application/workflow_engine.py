from __future__ import annotations

from dataclasses import dataclass, field

from deal_agent_platform.application.approval_service import ApprovalService
from deal_agent_platform.application.fact_service import FactIngestionService, IngestionOutcome
from deal_agent_platform.application.gate_service import GateRunResult, GateService
from deal_agent_platform.application.interfaces import ContextConfigStore, WorkingStateStore
from deal_agent_platform.domain import NormalizedEvent, WorkingContextState, utc_now


@dataclass
class EventProcessingResult:
    event_id: str
    skipped: bool
    skip_reason: str | None = None
    ingested_fact_ids: list[str] = field(default_factory=list)
    created_bundle_ids: list[str] = field(default_factory=list)


class DealAgentWorkflowEngine:
    """Temporal-like workflow core for one context (in-memory scaffold)."""

    def __init__(
        self,
        *,
        context_id: str,
        config_store: ContextConfigStore,
        state_store: WorkingStateStore,
        fact_service: FactIngestionService,
        gate_service: GateService,
        approval_service: ApprovalService,
    ) -> None:
        self.context_id = context_id
        self._config_store = config_store
        self._state_store = state_store
        self._fact_service = fact_service
        self._gate_service = gate_service
        self._approval_service = approval_service

    def on_event(self, event: NormalizedEvent) -> None:
        if event.context_id != self.context_id:
            raise ValueError(
                f"context mismatch: workflow={self.context_id} signal={event.context_id}"
            )
        state = self._state_store.get(self.context_id)
        state.pending_events.append(event)
        state.last_activity_at = utc_now()
        self._state_store.save(state)

    def on_approval_response(
        self,
        *,
        bundle_id: str,
        approved: bool,
        approver: str,
        notes: str | None = None,
    ) -> None:
        state = self._state_store.get(self.context_id)
        self._approval_service.apply_response(
            context_id=self.context_id,
            working_state=state,
            bundle_id=bundle_id,
            approved=approved,
            approver=approver,
            notes=notes,
        )
        self._state_store.save(state)

    def process_next_event(self) -> EventProcessingResult | None:
        state = self._state_store.get(self.context_id)
        if not state.pending_events:
            return None

        config = self._config_store.get(self.context_id)
        if config is None:
            raise KeyError(f"No context config found for {self.context_id}")

        event = state.pending_events.pop(0)
        ingestion: IngestionOutcome = self._fact_service.ingest_event(
            config=config,
            working_state=state,
            event=event,
        )

        if ingestion.skipped:
            self._state_store.save(state)
            return EventProcessingResult(
                event_id=event.event_id,
                skipped=True,
                skip_reason=ingestion.reason,
            )

        gate_result: GateRunResult = self._gate_service.run(
            config=config,
            working_state=state,
            triggering_event_id=event.event_id,
        )
        for bundle in gate_result.created_bundles:
            self._approval_service.submit_or_apply(bundle=bundle, working_state=state)

        self._state_store.save(state)
        return EventProcessingResult(
            event_id=event.event_id,
            skipped=False,
            ingested_fact_ids=[item.fact_id for item in ingestion.ingested_facts],
            created_bundle_ids=[bundle.bundle_id for bundle in gate_result.created_bundles],
        )

    def drain(self, *, max_events: int | None = None) -> list[EventProcessingResult]:
        results: list[EventProcessingResult] = []
        while True:
            if max_events is not None and len(results) >= max_events:
                break
            result = self.process_next_event()
            if result is None:
                break
            results.append(result)
        return results

    def get_status(self) -> dict[str, object]:
        state: WorkingContextState = self._state_store.get(self.context_id)
        return {
            "context_id": self.context_id,
            "pending_events": len(state.pending_events),
            "candidate_fields": sorted(state.candidate_fact_by_field.keys()),
            "conflicts": sorted(state.conflicts.keys()),
            "pending_bundles": sorted(state.pending_bundles.keys()),
            "gate_status": dict(state.gate_status),
            "last_activity_at": state.last_activity_at,
        }
