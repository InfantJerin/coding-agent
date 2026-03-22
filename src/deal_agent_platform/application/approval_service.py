from __future__ import annotations

from deal_agent_platform.application.interfaces import (
    ApprovalGateway,
    CommittedStateStore,
    FactLedger,
)
from deal_agent_platform.domain import (
    ApprovalTier,
    BundleStatus,
    DecisionBundle,
    FactLifecycle,
    WorkingContextState,
    utc_now,
)


class ApprovalService:
    def __init__(
        self,
        *,
        gateway: ApprovalGateway,
        committed_store: CommittedStateStore,
        ledger: FactLedger,
    ) -> None:
        self._gateway = gateway
        self._committed_store = committed_store
        self._ledger = ledger

    def submit_or_apply(
        self,
        *,
        bundle: DecisionBundle,
        working_state: WorkingContextState,
    ) -> None:
        if bundle.tier == ApprovalTier.AUTO_APPROVE:
            self.apply_response(
                context_id=bundle.context_id,
                working_state=working_state,
                bundle_id=bundle.bundle_id,
                approved=True,
                approver="system:auto",
                notes="auto-approved by tier policy",
            )
            return
        self._gateway.submit(bundle)

    def apply_response(
        self,
        *,
        context_id: str,
        working_state: WorkingContextState,
        bundle_id: str,
        approved: bool,
        approver: str,
        notes: str | None = None,
    ) -> DecisionBundle:
        bundle = working_state.pending_bundles.get(bundle_id)
        if bundle is None:
            raise KeyError(f"Unknown bundle_id: {bundle_id}")
        working_state.pending_bundles.pop(bundle_id, None)
        self._gateway.resolve(bundle_id)

        bundle.notes = notes
        bundle.approved_by = approver
        bundle.status = BundleStatus.APPROVED if approved else BundleStatus.REJECTED
        working_state.last_activity_at = utc_now()

        if not approved:
            return bundle

        committed_state = self._committed_store.get(context_id)
        for change in bundle.changes:
            fact = self._ledger.get(context_id, change.to_fact_id)
            if fact is None:
                continue
            fact.lifecycle = FactLifecycle.COMMITTED
            fact.approved_by = approver
            fact.committed_at = utc_now()
            committed_state.committed_fact_by_field[change.field] = fact.fact_id

            if change.from_fact_id:
                old_fact = self._ledger.get(context_id, change.from_fact_id)
                if old_fact is not None:
                    old_fact.lifecycle = FactLifecycle.SUPERSEDED
                    old_fact.status_reason = "superseded_after_bundle_approval"

        committed_state.last_updated_at = utc_now()
        self._committed_store.save(committed_state)
        return bundle
