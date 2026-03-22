from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from deal_agent_platform.domain import (
    ApprovalTier,
    CommittedBusinessState,
    ContextConfig,
    DecisionBundle,
    FactRecord,
    NormalizedEvent,
    WorkingContextState,
)


class FactLedger(Protocol):
    def append(self, fact: FactRecord) -> None:
        ...

    def get(self, context_id: str, fact_id: str) -> FactRecord | None:
        ...

    def list_by_context(self, context_id: str) -> list[FactRecord]:
        ...


class ContextConfigStore(Protocol):
    def put(self, config: ContextConfig) -> None:
        ...

    def get(self, context_id: str) -> ContextConfig | None:
        ...

    def list_all(self) -> list[ContextConfig]:
        ...


class WorkingStateStore(Protocol):
    def get(self, context_id: str) -> WorkingContextState:
        ...

    def save(self, state: WorkingContextState) -> None:
        ...


class CommittedStateStore(Protocol):
    def get(self, context_id: str) -> CommittedBusinessState:
        ...

    def save(self, state: CommittedBusinessState) -> None:
        ...


class ApprovalGateway(Protocol):
    def submit(self, bundle: DecisionBundle) -> None:
        ...

    def resolve(self, bundle_id: str) -> None:
        ...


class WorkflowSignalDispatcher(Protocol):
    def dispatch_event(self, event: NormalizedEvent) -> None:
        ...


@dataclass
class ActivityPolicyInput:
    tool_name: str
    agent_context_id: str
    tool_args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActivityPolicyDecision:
    allow: bool
    reason: str
    approval_required: ApprovalTier | None = None
    approvers: list[str] = field(default_factory=list)


class PolicyEngine(Protocol):
    def evaluate(self, input_data: ActivityPolicyInput) -> ActivityPolicyDecision:
        ...
