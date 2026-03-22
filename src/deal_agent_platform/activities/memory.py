from __future__ import annotations

from dataclasses import dataclass

from deal_agent_platform.application.interfaces import (
    CommittedStateStore,
    FactLedger,
    WorkingStateStore,
)


@dataclass
class MemorySnapshot:
    context_id: str
    candidate_fields: dict[str, str]
    conflicts: dict[str, list[str]]
    committed_fields: dict[str, str]
    total_facts: int


class MemoryActivities:
    def __init__(
        self,
        *,
        working_store: WorkingStateStore,
        committed_store: CommittedStateStore,
        ledger: FactLedger,
    ) -> None:
        self._working_store = working_store
        self._committed_store = committed_store
        self._ledger = ledger

    def load_agent_memory(self, context_id: str) -> MemorySnapshot:
        working = self._working_store.get(context_id)
        committed = self._committed_store.get(context_id)
        conflicts = {
            field: list(conflict.active_fact_ids)
            for field, conflict in working.conflicts.items()
        }
        return MemorySnapshot(
            context_id=context_id,
            candidate_fields=dict(working.candidate_fact_by_field),
            conflicts=conflicts,
            committed_fields=dict(committed.committed_fact_by_field),
            total_facts=len(self._ledger.list_by_context(context_id)),
        )

    def save_agent_memory(self, context_id: str) -> MemorySnapshot:
        # In-memory scaffold has no external persistence to flush, so save/load are equivalent.
        return self.load_agent_memory(context_id)
