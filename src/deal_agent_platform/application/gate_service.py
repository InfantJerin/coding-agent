from __future__ import annotations

from dataclasses import dataclass

from deal_agent_platform.application.interfaces import CommittedStateStore, FactLedger
from deal_agent_platform.domain import (
    ContextConfig,
    DecisionBundle,
    GateEvaluation,
    ProposedChange,
    ReadinessGate,
    WorkingContextState,
    new_id,
    parse_utc,
    utc_now,
)


@dataclass
class GateRunResult:
    evaluations: dict[str, GateEvaluation]
    created_bundles: list[DecisionBundle]


class GateService:
    def __init__(self, ledger: FactLedger, committed_store: CommittedStateStore) -> None:
        self._ledger = ledger
        self._committed_store = committed_store

    def run(
        self,
        *,
        config: ContextConfig,
        working_state: WorkingContextState,
        triggering_event_id: str,
    ) -> GateRunResult:
        evaluations: dict[str, GateEvaluation] = {}
        created_bundles: list[DecisionBundle] = []

        for gate_id, gate in config.readiness_gates.items():
            evaluation = self._evaluate_gate(gate=gate, working_state=working_state)
            evaluations[gate_id] = evaluation
            working_state.gate_status[gate_id] = evaluation.satisfied
            if not evaluation.satisfied:
                continue
            bundle = self._build_decision_bundle(
                context_id=config.context_id,
                gate=gate,
                working_state=working_state,
                triggering_event_id=triggering_event_id,
            )
            if bundle is None:
                continue
            working_state.pending_bundles[bundle.bundle_id] = bundle
            created_bundles.append(bundle)

        working_state.last_activity_at = utc_now()
        return GateRunResult(evaluations=evaluations, created_bundles=created_bundles)

    def _evaluate_gate(
        self,
        *,
        gate: ReadinessGate,
        working_state: WorkingContextState,
    ) -> GateEvaluation:
        evaluation = GateEvaluation(gate_id=gate.gate_id, satisfied=False)
        for gate_dep in gate.requires_gates:
            if not working_state.gate_status.get(gate_dep, False):
                evaluation.blocked_by_gates.append(gate_dep)

        for field_name in gate.requires_fields:
            fact_id = working_state.candidate_fact_by_field.get(field_name)
            if fact_id is None:
                evaluation.missing_fields.append(field_name)
                continue
            if field_name in working_state.conflicts:
                evaluation.conflicted_fields.append(field_name)
                continue

            fact = self._ledger.get(working_state.context_id, fact_id)
            if fact is None:
                evaluation.missing_fields.append(field_name)
                continue
            if fact.provenance.confidence < gate.min_confidence:
                evaluation.low_confidence_fields.append(field_name)
            if gate.allowed_sources and fact.provenance.source not in set(gate.allowed_sources):
                evaluation.low_confidence_fields.append(field_name)
            max_age = gate.max_age()
            if max_age is not None:
                age = parse_utc(utc_now()) - parse_utc(fact.provenance.observed_at)
                if age > max_age:
                    evaluation.stale_fields.append(field_name)

        evaluation.satisfied = not any(
            [
                evaluation.missing_fields,
                evaluation.conflicted_fields,
                evaluation.stale_fields,
                evaluation.low_confidence_fields,
                evaluation.blocked_by_gates,
            ]
        )
        return evaluation

    def _build_decision_bundle(
        self,
        *,
        context_id: str,
        gate: ReadinessGate,
        working_state: WorkingContextState,
        triggering_event_id: str,
    ) -> DecisionBundle | None:
        committed = self._committed_store.get(context_id)
        changes: list[ProposedChange] = []
        for field_name in gate.requires_fields:
            candidate_fact_id = working_state.candidate_fact_by_field.get(field_name)
            if candidate_fact_id is None:
                continue
            committed_fact_id = committed.committed_fact_by_field.get(field_name)
            if committed_fact_id == candidate_fact_id:
                continue
            changes.append(
                ProposedChange(
                    field=field_name,
                    from_fact_id=committed_fact_id,
                    to_fact_id=candidate_fact_id,
                    reason=f"gate={gate.gate_id}",
                )
            )
        if not changes:
            return None
        return DecisionBundle(
            bundle_id=new_id("bundle"),
            context_id=context_id,
            title=f"{gate.gate_id} promotion",
            tier=gate.approval_tier,
            changes=changes,
            evidence_event_ids=[triggering_event_id],
        )
