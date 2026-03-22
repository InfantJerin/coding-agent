from __future__ import annotations

from dataclasses import dataclass, field

from deal_agent_platform.application import (
    ApprovalService,
    DealAgentWorkflowEngine,
    FactIngestionService,
    GateService,
)
from deal_agent_platform.channel_bridge import ChannelBridgeService, ContextResolver, EventNormalizer
from deal_agent_platform.domain import ContextConfig, NormalizedEvent
from deal_agent_platform.infrastructure import (
    InMemoryApprovalGateway,
    InMemoryCommittedStateStore,
    InMemoryContextConfigStore,
    InMemoryFactLedger,
    InMemoryWorkflowDispatcher,
    InMemoryWorkingStateStore,
)
from deal_agent_platform.policy import OpaLikePolicyEngine
from deal_agent_platform.workflows import DealAgentWorkflow


@dataclass
class InMemoryDealAgentPlatform:
    context_store: InMemoryContextConfigStore
    working_store: InMemoryWorkingStateStore
    committed_store: InMemoryCommittedStateStore
    ledger: InMemoryFactLedger
    approval_gateway: InMemoryApprovalGateway
    workflow_dispatcher: InMemoryWorkflowDispatcher
    policy_engine: OpaLikePolicyEngine
    channel_bridge: ChannelBridgeService
    workflows: dict[str, DealAgentWorkflow] = field(default_factory=dict)

    def register_context(self, config: ContextConfig, *, start_workflow: bool = True) -> None:
        self.context_store.put(config)
        if start_workflow:
            self.start_workflow(config.context_id)

    def start_workflow(self, context_id: str) -> DealAgentWorkflow:
        if context_id in self.workflows:
            return self.workflows[context_id]
        engine = DealAgentWorkflowEngine(
            context_id=context_id,
            config_store=self.context_store,
            state_store=self.working_store,
            fact_service=FactIngestionService(ledger=self.ledger),
            gate_service=GateService(ledger=self.ledger, committed_store=self.committed_store),
            approval_service=ApprovalService(
                gateway=self.approval_gateway,
                committed_store=self.committed_store,
                ledger=self.ledger,
            ),
        )
        workflow = DealAgentWorkflow(engine=engine)
        self.workflows[context_id] = workflow
        self.workflow_dispatcher.register_workflow(context_id, workflow)
        return workflow

    def signal_event(self, event: NormalizedEvent) -> None:
        self.workflow_dispatcher.dispatch_event(event)

    def ingest_raw_event(self, raw_event: dict) -> NormalizedEvent:
        return self.channel_bridge.ingest(raw_event)


def build_in_memory_platform() -> InMemoryDealAgentPlatform:
    context_store = InMemoryContextConfigStore()
    working_store = InMemoryWorkingStateStore()
    committed_store = InMemoryCommittedStateStore()
    ledger = InMemoryFactLedger()
    approval_gateway = InMemoryApprovalGateway()
    workflow_dispatcher = InMemoryWorkflowDispatcher()
    policy_engine = OpaLikePolicyEngine(config_store=context_store)
    bridge = ChannelBridgeService(
        resolver=ContextResolver(config_store=context_store),
        normalizer=EventNormalizer(),
        dispatcher=workflow_dispatcher,
    )
    return InMemoryDealAgentPlatform(
        context_store=context_store,
        working_store=working_store,
        committed_store=committed_store,
        ledger=ledger,
        approval_gateway=approval_gateway,
        workflow_dispatcher=workflow_dispatcher,
        policy_engine=policy_engine,
        channel_bridge=bridge,
    )
