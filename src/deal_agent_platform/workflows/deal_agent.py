from __future__ import annotations

from deal_agent_platform.application.workflow_engine import (
    DealAgentWorkflowEngine,
    EventProcessingResult,
)
from deal_agent_platform.domain import NormalizedEvent


class DealAgentWorkflow:
    """
    Scaffold facade mirroring Temporal workflow handlers:
    - on_event: signal handler
    - on_approval_response: signal handler
    - get_status: query handler
    """

    def __init__(self, engine: DealAgentWorkflowEngine) -> None:
        self._engine = engine

    def on_event(self, event: NormalizedEvent) -> None:
        self._engine.on_event(event)

    def on_approval_response(
        self,
        *,
        bundle_id: str,
        approved: bool,
        approver: str,
        notes: str | None = None,
    ) -> None:
        self._engine.on_approval_response(
            bundle_id=bundle_id,
            approved=approved,
            approver=approver,
            notes=notes,
        )

    def run_until_idle(self) -> list[EventProcessingResult]:
        return self._engine.drain()

    def get_status(self) -> dict[str, object]:
        return self._engine.get_status()
