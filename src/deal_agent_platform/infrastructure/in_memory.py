from __future__ import annotations

from collections import defaultdict

from deal_agent_platform.application.interfaces import (
    ApprovalGateway,
    CommittedStateStore,
    ContextConfigStore,
    FactLedger,
    WorkflowSignalDispatcher,
)
from deal_agent_platform.domain import (
    CommittedBusinessState,
    ContextConfig,
    DecisionBundle,
    FactRecord,
    NormalizedEvent,
    WorkingContextState,
)


class InMemoryFactLedger(FactLedger):
    def __init__(self) -> None:
        self._by_context: dict[str, dict[str, FactRecord]] = defaultdict(dict)

    def append(self, fact: FactRecord) -> None:
        self._by_context[fact.context_id][fact.fact_id] = fact

    def get(self, context_id: str, fact_id: str) -> FactRecord | None:
        return self._by_context.get(context_id, {}).get(fact_id)

    def list_by_context(self, context_id: str) -> list[FactRecord]:
        return list(self._by_context.get(context_id, {}).values())


class InMemoryContextConfigStore(ContextConfigStore):
    def __init__(self) -> None:
        self._configs: dict[str, ContextConfig] = {}

    def put(self, config: ContextConfig) -> None:
        self._configs[config.context_id] = config

    def get(self, context_id: str) -> ContextConfig | None:
        return self._configs.get(context_id)

    def list_all(self) -> list[ContextConfig]:
        return list(self._configs.values())


class InMemoryWorkingStateStore:
    def __init__(self) -> None:
        self._states: dict[str, WorkingContextState] = {}

    def get(self, context_id: str) -> WorkingContextState:
        if context_id not in self._states:
            self._states[context_id] = WorkingContextState(context_id=context_id)
        return self._states[context_id]

    def save(self, state: WorkingContextState) -> None:
        self._states[state.context_id] = state


class InMemoryCommittedStateStore(CommittedStateStore):
    def __init__(self) -> None:
        self._states: dict[str, CommittedBusinessState] = {}

    def get(self, context_id: str) -> CommittedBusinessState:
        if context_id not in self._states:
            self._states[context_id] = CommittedBusinessState(context_id=context_id)
        return self._states[context_id]

    def save(self, state: CommittedBusinessState) -> None:
        self._states[state.context_id] = state


class InMemoryApprovalGateway(ApprovalGateway):
    def __init__(self) -> None:
        self.pending: dict[str, DecisionBundle] = {}

    def submit(self, bundle: DecisionBundle) -> None:
        self.pending[bundle.bundle_id] = bundle

    def resolve(self, bundle_id: str) -> None:
        self.pending.pop(bundle_id, None)


class InMemoryWorkflowDispatcher(WorkflowSignalDispatcher):
    def __init__(self) -> None:
        self._handlers: dict[str, object] = {}

    def register_workflow(self, context_id: str, workflow: object) -> None:
        self._handlers[context_id] = workflow

    def dispatch_event(self, event: NormalizedEvent) -> None:
        workflow = self._handlers.get(event.context_id)
        if workflow is None:
            raise KeyError(f"No workflow registered for context_id={event.context_id}")
        on_event = getattr(workflow, "on_event")
        on_event(event)
