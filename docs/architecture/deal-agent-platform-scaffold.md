# Deal Agent Platform Scaffold (Implementation Notes)

This scaffold implements the design direction from:

- `docs/architecture/deal-agent-platform.md`
- `docs/architecture/deal_agent_design_review_precise.md`
- `docs/architecture/deal-agent-platform-architecture-v2.html`

## What Was Implemented

## Layered package structure

- `src/deal_agent_platform/domain/`
- `src/deal_agent_platform/application/`
- `src/deal_agent_platform/channel_bridge/`
- `src/deal_agent_platform/policy/`
- `src/deal_agent_platform/workflows/`
- `src/deal_agent_platform/activities/`
- `src/deal_agent_platform/infrastructure/`

## Key architecture decisions reflected in code

1. Fact ledger with provenance
- `FactRecord` + `FactProvenance` model extracted facts with source, version, timestamp, confidence.
- Lifecycle states included: observed/extracted/candidate/conflicted/approved/committed/superseded.

2. Working memory vs committed business state
- `WorkingContextState`: candidates, conflicts, pending bundles, gate status.
- `CommittedBusinessState`: promoted facts only.

3. Conflict-aware promotion
- `FactIngestionService` resolves candidates with source priority and version-aware supersession.
- Ties with different values are marked as explicit conflicts.

4. Event and artifact dedupe + lineage
- `seen_event_ids` and `seen_artifact_hashes` in working state.
- `document_lineage` tracks parent references when provided by events.

5. Readiness gates beyond field presence
- `GateService` evaluates:
  - required fields
  - conflicts
  - freshness
  - confidence
  - gate dependencies

6. Decision bundle approvals
- `GateService` emits `DecisionBundle` objects.
- `ApprovalService` applies approvals to commit multiple field changes together.
- `ApprovalTier.AUTO_APPROVE` supports low-risk automatic progression.

7. Policy 4-check pipeline
- `OpaLikePolicyEngine` evaluates:
  - tool allowlist/denylist
  - context boundary
  - data scope
  - approval tier
- Starter Rego policy scaffold added at `policy/policies/agent.rego`.

## Runtime scaffold behavior

- `DealAgentWorkflowEngine` models Temporal-like workflow behavior:
  - `on_event`
  - `on_approval_response`
  - `get_status` query
  - `drain` loop for event processing
- `ChannelBridgeService` routes raw channel events into normalized workflow signals.

## Included tests

`tests/test_deal_agent_scaffold.py` verifies:

- bridge + workflow + approval commit flow
- duplicate event handling
- conflict detection behavior
- auto-approval path
- policy boundary denial

## Intended next steps

1. Replace in-memory adapters with real implementations (S3/OpenSearch/DB/Teams/Temporal).
2. Swap `OpaLikePolicyEngine` with real OPA evaluation (bundle + decision logging).
3. Replace workflow facade with Temporal Python SDK workflow + activities.
4. Persist fact ledger append-only transitions to S3 or Postgres.
