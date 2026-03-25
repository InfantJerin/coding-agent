# Deal Intelligence Agent Platform — System Architecture v2

## 1. Overview

### 1.1 Purpose

A context-scoped agentic platform that monitors business activity across an enterprise ecosystem — email, document repositories, application logs, transactional systems — and autonomously extracts information, detects discrepancies, runs computations, and takes action within defined approval boundaries.

Each **context** (a deal, a compliance review, a counterparty relationship) gets its own agent that:
- Observes events from multiple channels tagged with its context ID
- Reads and extracts terms from incoming documents (LLM intelligence)
- Evaluates readiness against deterministic rules (not LLM)
- Queries transactional systems for current state
- Runs calculations (risk, exposure, compliance checks)
- Communicates progress and requests approvals from humans
- Promotes approved facts to systems of record

### 1.2 Design Principles

| # | Principle | Rationale |
|---|-----------|-----------|
| 1 | **File-based agent memory, tools for everything else** | Agent owns only its own state (S3 files). All business data accessed via scoped tools. Inspired by OpenClaw's simplicity — JSONL events, Markdown memory, JSON state. |
| 2 | **Context ID is the universal partition key** | Every event, document, memory file, tool call, and audit entry is tagged with a context ID. This is the boundary for isolation, access control, and data scoping. |
| 3 | **Phase-based lifecycle, not eternal workflows** | Each context progresses through bounded phases (origination, amendment, servicing). Each active phase is a Temporal Workflow. Servicing uses schedule-triggered short-lived workflows. No workflow runs longer than months. |
| 4 | **Deal type templates define the lifecycle** | Each deal type (revolver, term loan, delayed draw) has a versioned template that defines phases, readiness gates, and available activities. Business teams maintain templates. New use cases require template changes, not code changes. |
| 5 | **LLM extracts, rules evaluate, humans approve** | LLM intelligence is confined to extraction and reasoning about document content. Gate evaluation is deterministic rules. Action execution requires human approval for anything above auto-approve tier. |
| 6 | **Deny-by-default policy (OPA)** | Every Activity evaluated by OPA. OPA is a deterministic bouncer — allowlist checks, context boundary enforcement, approval tier classification. No LLM reasoning in policy evaluation. |
| 7 | **Four-layer state model** | Raw evidence → Fact ledger → Working context → Committed business state. Memory is where the agent thinks. Business state is where the firm acts. |
| 8 | **Separation of plumbing and intelligence** | Temporal handles orchestration, durability, retries, and scaling. The agent handles reasoning (LLM calls). Channel Bridge handles event ingestion. Rules handle gate evaluation. |

### 1.3 Key Changes from v1

| Area | v1 | v2 | Rationale |
|------|----|----|-----------|
| **Workflow lifecycle** | One eternal workflow per context | Phase-based: bounded workflows + schedule-triggered servicing | Deals can span 50 years. No workflow should run that long. |
| **Readiness gates** | Hardcoded per deal in context.yaml | Deal type templates with deterministic rule evaluation | Reduces per-deal configuration. New deal types require template, not code. |
| **Gate evaluation** | Implicit (field presence only) | Deterministic rules: present + not conflicted + fresh + source quality + approval-cleared | Prevents premature triggering on incomplete or contested data. |
| **Agent roles** | Three named agents (Analyst/Observer/Calculator) | Three sequential phases in the main loop (extract → evaluate → act) | These are workflow phases, not separate agents. |
| **State model** | Flat: extracted_terms.json with last-write-wins | Four layers (A–D) with fact ledger, provenance, and conflict-aware promotion | Prevents silent overwrites. Separates agent thinking from firm action. |
| **Approval model** | Per-tool-call approvals | Decision bundle approvals | Reduces approval fatigue. Groups related state changes. |
| **Deduplication** | Not specified | Three-layer dedupe: event ID, content hash, version lineage | Prevents duplicate processing and tracks document evolution. |

---

## 2. Deal Type Templates

### 2.1 Purpose

Deal type templates define the lifecycle pattern for a category of deals. They are the primary mechanism for extending the platform to new use cases **without writing code**.

A template specifies:
- What **phases** the deal progresses through
- What **readiness gates** exist in each phase
- What **activities** are triggered when gates open
- What **approval tiers** apply to each activity
- What **scheduled events** occur during servicing

### 2.2 Template Structure

```yaml
# Template: stored at s3://agent-templates/{deal_type}.yaml
# Versioned, reviewed in PRs, testable

template_id: revolving_credit_facility
version: "2.3"
display_name: "Revolving Credit Facility"
updated_by: "compliance-team"
updated_at: "2026-03-15T10:00:00Z"

# --- Phases ---
# Each phase is a bounded processing window.
# A deal progresses through phases sequentially.
# Each active phase runs as a Temporal Workflow.
# Servicing phases use schedule-triggered workflows.

phases:
  origination:
    type: event_loop          # persistent event loop, processes events as they arrive
    description: "Active deal setup, document extraction, structuring"
    gates:
      kyc_initiation:
        requires_fields:
          - entity_name
          - entity_type
          - jurisdiction
          - beneficial_owners
          - tax_id
        rule: all_present_and_not_conflicted
        triggers: initiate_kyc
        approval_tier: single_approval
        timeout: 5d
        on_timeout: escalate

      deal_structuring:
        requires_fields:
          - facility_amount
          - facility_type
          - maturity_date
          - pricing_grid
          - roles
          - collateral_type
          - covenant_terms
        rule: all_present_and_not_conflicted
        triggers: create_deal_structures
        approval_tier: maker_checker
        timeout: 7d
        on_timeout: notify_and_wait

      roe_calculation:
        requires_fields:
          - facility_amount
          - pricing_grid
          - roles
          - capital_allocation
          - funding_cost
        requires_gates: [deal_structuring]
        rule: all_present_and_source_quality_above(0.8)
        triggers: calculate_roe_across_structures
        approval_tier: auto_approve
        timeout: 1d

      graylist_screening:
        requires_fields:
          - entity_name
          - beneficial_owners
          - jurisdiction
        rule: all_present_and_not_conflicted
        triggers: initiate_graylist_walker
        approval_tier: single_approval
        timeout: 3d
        on_timeout: escalate

      committee_memo:
        requires_gates: [deal_structuring, roe_calculation, kyc_initiation, graylist_screening]
        rule: all_dependencies_completed
        triggers: initiate_committee_memo_review
        approval_tier: maker_checker
        timeout: 10d
        on_timeout: escalate

      booking:
        requires_gates: [committee_memo]
        rule: all_dependencies_completed_and_approved
        triggers: book_deal_to_system_of_record
        approval_tier: four_eyes
        timeout: 5d

    completion_condition: booking.completed
    handoff_to: servicing

  amendment:
    type: event_loop          # activated on-demand when amendment is needed
    description: "Deal modification — re-extracts affected terms, re-evaluates gates"
    gates:
      amendment_extraction:
        requires_fields:
          - amendment_type
          - affected_terms
          - effective_date
        rule: all_present_and_not_conflicted
        triggers: process_amendment_terms
        approval_tier: single_approval

      amended_committee_review:
        requires_gates: [amendment_extraction]
        rule: all_dependencies_completed
        triggers: initiate_amendment_committee_review
        approval_tier: maker_checker

      amendment_booking:
        requires_gates: [amended_committee_review]
        rule: all_dependencies_completed_and_approved
        triggers: book_amendment
        approval_tier: four_eyes

    completion_condition: amendment_booking.completed
    handoff_to: servicing

  servicing:
    type: schedule_triggered   # no persistent event loop — short-lived workflows on schedule
    description: "Periodic compliance, rate resets, covenant monitoring"
    scheduled_events:
      - cron: "0 9 * * MON"
        event_type: weekly_position_check
        workflow: ServicingCheckWorkflow

      - cron: "0 9 1 */3 *"    # quarterly
        event_type: quarterly_compliance_check
        workflow: ComplianceCheckWorkflow
        gates:
          compliance_verification:
            requires_fields:
              - compliance_certificate_received
              - positions_current
            rule: all_present_and_fresh(max_age=30d)
            triggers: verify_compliance
            approval_tier: single_approval

      - trigger: on_document_received(doc_type=rate_notice)
        event_type: rate_reset_processing
        workflow: RateResetWorkflow
        gates:
          rate_verification:
            requires_fields:
              - new_rate
              - effective_date
              - rate_basis
            rule: all_present_and_not_conflicted
            triggers: verify_and_apply_rate_reset
            approval_tier: single_approval

    # If servicing detects need for amendment:
    escalation_to: amendment

# --- Document Precedence ---
# When facts conflict, higher-precedence source wins.
# Deterministic, auditable, editable by business.
document_precedence:
  - credit_agreement        # highest — overwrites all below
  - amendment
  - committee_memo
  - term_sheet
  - rate_notice
  - compliance_certificate  # lowest — never overwrites above

# --- Available Activities ---
# All activities the agent can trigger in this deal type.
# Each must have a corresponding Activity implementation in the worker pool.
available_activities:
  - initiate_kyc
  - create_deal_structures
  - calculate_roe_across_structures
  - initiate_graylist_walker
  - initiate_committee_memo_review
  - book_deal_to_system_of_record
  - process_amendment_terms
  - initiate_amendment_committee_review
  - book_amendment
  - verify_compliance
  - verify_and_apply_rate_reset

# --- Agent Configuration ---
agent:
  model: "anthropic/claude-sonnet-4-6"
  max_turns_per_wake: 20
  extraction_profile: "finance-docs"
```

### 2.3 Template Lifecycle

Templates are versioned and maintained by business/compliance teams:

```
1. Business identifies new deal type or process change
2. Template author creates/updates YAML (PR review required)
3. Template tested against synthetic deal scenarios
4. Template deployed to s3://agent-templates/
5. New deals created with this template pick up changes automatically
6. Existing deals optionally migrated via admin tool
```

Template changes that add new gates or activities don't require code changes — only a new Activity implementation if the triggered action doesn't already exist.

---

## 3. Phase-Based Lifecycle

### 3.1 Why Not One Eternal Workflow

| Concern | Impact |
|---------|--------|
| Deals can span 50+ years (loan servicing maturity) | No Temporal workflow should run that long |
| Infrastructure changes over decades | Temporal API, cluster, persistence store will change |
| Workflow code evolves | Breaking changes to workflow logic need clean boundaries |
| Resource efficiency | A servicing deal that gets one event per quarter doesn't need a persistent event loop |

### 3.2 Phase Types

#### Event Loop Phase (origination, amendment)

Used when events arrive unpredictably and the agent needs to maintain evolving state.

```
┌──────────────────────────────────────────────────────────────────────┐
│  EVENT LOOP PHASE (e.g., origination)                                │
│                                                                       │
│  Temporal Workflow: DealPhaseWorkflow                                 │
│  Workflow ID: {context_id}:{phase_name}:{phase_instance}             │
│    e.g., deal-abc-2026:origination:1                                 │
│                                                                       │
│  Main Loop:                                                          │
│    1. Load deal type template + fact ledger + working state          │
│    2. WAIT for events (wait_condition — zero compute)                │
│    3. EVENT CLASSIFIER: route to processing path                     │
│       - incremental document → extract, merge, evaluate              │
│       - replacement document → re-baseline affected facts            │
│       - query → pull data, respond, no extraction                    │
│       - scheduled check → evaluate without new document              │
│    4. EXTRACT PHASE: LLM extracts terms with provenance             │
│       → writes to fact ledger (Layer B)                              │
│    5. EVALUATE PHASE: deterministic rules check all gates            │
│       → gate satisfied? enqueue action with approval tier            │
│    6. ACT PHASE: execute approved actions as Activities              │
│    7. Save state, check history size (continue_as_new if needed)     │
│    8. Check completion_condition                                      │
│       - if met: complete workflow, hand off to next phase            │
│       - if not: loop back to step 2                                  │
│                                                                       │
│  Completion:                                                         │
│    → Archives phase state to S3                                      │
│    → Writes phase_completed event to transactional DB                │
│    → Context Registry starts next phase                              │
└──────────────────────────────────────────────────────────────────────┘
```

#### Schedule-Triggered Phase (servicing)

Used when events are periodic and predictable. No persistent event loop.

```
┌──────────────────────────────────────────────────────────────────────┐
│  SCHEDULE-TRIGGERED PHASE (e.g., servicing)                          │
│                                                                       │
│  No persistent workflow. Temporal Schedules trigger short-lived       │
│  workflows when events occur.                                        │
│                                                                       │
│  For each scheduled_event in the template:                           │
│    Temporal Schedule:                                                 │
│      cron/trigger → starts ServicingWorkflow                         │
│      → loads deal context from S3 + transactional DB                 │
│      → processes the specific event                                  │
│      → evaluates relevant gates                                      │
│      → executes approved actions                                     │
│      → saves updated state                                           │
│      → workflow COMPLETES (short-lived)                              │
│                                                                       │
│  For unexpected document events (e.g., amendment notice):            │
│    Channel Bridge detects event for servicing-phase deal             │
│    → Context Registry checks: does this need an amendment phase?     │
│    → If yes: starts amendment phase workflow (event_loop type)       │
│    → Amendment workflow runs until complete                          │
│    → Hands back to servicing schedules                               │
│                                                                       │
│  Duration: indefinite (schedules persist), but each workflow is      │
│  short-lived (minutes to hours, never months).                       │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.3 Phase Transitions

```
                     ┌──────────────┐
                     │  Deal Created │
                     └──────┬───────┘
                            │ Context Registry creates phase workflow
                            ▼
                ┌───────────────────────┐
                │  ORIGINATION (event   │
                │  loop, weeks/months)  │
                │                       │
                │  booking gate         │
                │  completed ──────────►│───┐
                └───────────────────────┘   │
                                            │ handoff_to: servicing
                                            ▼
                ┌───────────────────────┐
                │  SERVICING (schedule  │◄──────────────────┐
                │  triggered, years)    │                    │
                │                       │                    │
                │  Amendment needed? ──►│───┐                │
                └───────────────────────┘   │                │
                                            │ escalation_to  │
                                            ▼                │
                ┌───────────────────────┐   │                │
                │  AMENDMENT (event     │   │                │
                │  loop, weeks/months)  │   │                │
                │                       │   │                │
                │  amendment booked ───►│───┘ handoff back   │
                └───────────────────────┘──────────────────►─┘

                Deal maturity / payoff:
                  → Context Registry terminates schedules
                  → Archives all state
                  → Marks context as closed
```

---

## 4. Four-Layer State Model

### 4.1 Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                       │
│  Layer A: RAW EVIDENCE                                               │
│  Documents, emails, event payloads, system snapshots                 │
│  Storage: OpenSearch (indexed content), S3 (original files)          │
│  Who writes: Channel Bridge (on ingestion)                           │
│  Who reads: Agent (via search Activities)                            │
│  Immutable. Never modified after ingestion.                          │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Layer B: FACT LEDGER                                                │
│  Versioned extracted facts with full provenance                      │
│  Storage: S3 (fact_ledger.jsonl) + transactional DB (queryable)     │
│  Who writes: Agent (extraction phase)                                │
│  Who reads: Agent (gate evaluation), dashboards, audit              │
│  Append-only. Facts are never deleted — superseded facts remain      │
│  in the ledger with status = superseded.                             │
│                                                                       │
│  Each fact record:                                                   │
│  {                                                                   │
│    "fact_id": "f-a1b2c3",                                           │
│    "field": "facility_amount",                                       │
│    "value": 250000000,                                               │
│    "source": "credit_agreement_v2.pdf",                              │
│    "source_type": "credit_agreement",                                │
│    "source_version": "v2",                                           │
│    "confidence": 0.95,                                               │
│    "status": "candidate",                                            │
│    "observed_at": "2026-03-20T14:30:00Z",                           │
│    "extracted_by": "claude-sonnet-4-6",                              │
│    "approved_by": null,                                              │
│    "committed_at": null,                                             │
│    "supersedes": "f-x9y8z7",                                        │
│    "superseded_by": null                                             │
│  }                                                                   │
│                                                                       │
│  Fact status lifecycle:                                              │
│    observed → extracted → candidate → approved → committed           │
│                              ↓                      ↓                │
│                          conflicted              superseded          │
│                              ↓                                       │
│                     (human resolution)                               │
│                              ↓                                       │
│                          candidate                                   │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Layer C: WORKING CONTEXT STATE                                      │
│  Best candidate values, active conflicts, pending approvals,         │
│  gate status, agent reasoning memory                                 │
│  Storage: S3 (MEMORY.md, state.json, gate_status.json)              │
│  Who writes: Agent (during processing)                               │
│  Who reads: Agent (on wake-up), dashboards (via Temporal Query)     │
│  Mutable. Rebuilt from fact ledger if needed.                        │
│                                                                       │
│  This is where the agent thinks.                                     │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Layer D: COMMITTED BUSINESS STATE                                   │
│  Only approved, promoted data written to operational systems         │
│  Storage: Transactional DB (Postgres)                                │
│  Who writes: Agent (only via promotion Activities, after approval)   │
│  Who reads: Agent, dashboards, downstream systems, reports           │
│  System of record. Cross-context queryable.                          │
│                                                                       │
│  This is where the firm acts.                                        │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Conflict Resolution

When two facts compete for the same field:

```
1. DOCUMENT PRECEDENCE (deterministic, from deal type template)
   credit_agreement > amendment > term_sheet > rate_notice > compliance_cert
   → Higher-precedence source wins automatically.

2. VERSION-AWARE SUPERSESSION
   Same source, newer version → new fact supersedes old fact.
   credit_agreement_v2.pdf supersedes credit_agreement_v1.pdf.
   → Supersession is automatic. Old fact status → superseded.

3. GENUINE CONFLICT (same precedence, different values)
   → Both facts marked status = conflicted.
   → Gate evaluation pauses for affected gates.
   → Conflict object created with both values + sources.
   → Routed to human via Teams for resolution.
   → Human selects winner → winning fact → candidate, loser → superseded.
```

### 4.3 Deduplication Pipeline

Three layers of deduplication in the Channel Bridge:

```
1. EVENT DEDUPE
   Key: event_id / message_id / file_version_id
   → Reject if event already processed (idempotency key in transactional DB)

2. ARTIFACT DEDUPE
   Key: content hash (SHA-256 of normalized text)
   → Reject if identical content already ingested for this context
   → Allows same document from different channels to be deduplicated

3. DOCUMENT LINEAGE
   Detection: filename patterns, metadata, content comparison
   → Classify as: draft / final / amendment / superseding version
   → Link to previous versions in the fact ledger
   → Trigger re-extraction only for changed sections when possible
```

---

## 5. Readiness Gate Evaluation

### 5.1 Deterministic Rules, Not LLM Reasoning

Gate evaluation is a critical design boundary: **the LLM extracts facts, but rules evaluate gates.**

The LLM's job is to read a 600-page credit agreement and correctly identify `beneficial_owners` from a buried schedule. The rule engine's job is to check whether `beneficial_owners` exists in the fact ledger with an acceptable status.

This separation ensures that gate triggering is:
- **Predictable** — same facts always produce the same gate result
- **Auditable** — the rule that fired can be inspected without understanding LLM reasoning
- **Testable** — rules can be unit tested with synthetic fact ledger states
- **Fast** — no LLM call needed, evaluation is milliseconds

### 5.2 Rule Types

| Rule | Semantics |
|------|-----------|
| `all_present_and_not_conflicted` | All required fields have at least one fact with status ∈ {candidate, approved, committed} and no fact with status = conflicted for the same field. |
| `all_present_and_fresh(max_age=30d)` | All present + not conflicted + most recent fact for each field is within max_age. |
| `all_present_and_source_quality_above(threshold)` | All present + not conflicted + confidence ≥ threshold for each field. |
| `all_dependencies_completed` | All gates listed in `requires_gates` have status = completed. |
| `all_dependencies_completed_and_approved` | All dependency gates completed + all triggered actions approved by humans. |

Rules are composable. New rules can be added to the rule engine without modifying workflow code — they're registered functions that take a fact ledger snapshot and a gate definition as input and return satisfied/unsatisfied with a reason.

### 5.3 Gate Lifecycle

```
Gate statuses:
  unsatisfied          — required fields missing or rules not met
  satisfied            — all rules pass, action ready to trigger
  action_pending       — action enqueued, awaiting approval
  action_approved      — approval received, executing
  completed            — action executed successfully
  paused               — underlying facts changed during approval, re-evaluation needed

Backward transition:
  action_pending → unsatisfied
    When: a fact that satisfied the gate is superseded or enters conflicted status
          while the approval is still pending.
    Action: withdraw approval card from Teams, re-evaluate gate from scratch.
    Rationale: don't approve actions based on stale or contested data.
```

---

## 6. System Architecture

### 6.1 Component Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                     DEAL INTELLIGENCE AGENT PLATFORM v2                      │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                        CHANNEL BRIDGE                                  │ │
│  │                                                                        │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────┐   │ │
│  │  │ Power        │ │ SFTP         │ │ BQL        │ │ Manual       │   │ │
│  │  │ Automate     │ │ Watcher      │ │ Consumer   │ │ Trigger      │   │ │
│  │  └──────┬───────┘ └──────┬───────┘ └─────┬──────┘ └──────┬───────┘   │ │
│  │         └────────────────┴───────────────┴────────────────┘           │ │
│  │                                  │                                    │ │
│  │                    ┌─────────────┼──────────────┐                    │ │
│  │                    │             │              │                     │ │
│  │              ┌─────▼─────┐ ┌────▼─────┐ ┌─────▼──────┐              │ │
│  │              │ Context ID│ │  Dedupe  │ │  Signal    │              │ │
│  │              │ Resolver  │ │ Pipeline │ │  Dispatch  │              │ │
│  │              │(determini-│ │(event ID │ │            │              │ │
│  │              │ stic)     │ │+hash     │ │            │              │ │
│  │              │           │ │+lineage) │ │            │              │ │
│  │              └───────────┘ └──────────┘ └─────┬──────┘              │ │
│  └───────────────────────────────────────────────┼───────────────────────┘ │
│                                                   │                        │
│                                          Temporal Signal                   │
│                                                   │                        │
│  ┌────────────────────────────────────────────────┼───────────────────────┐│
│  │         CONTEXT REGISTRY                       │                       ││
│  │                                                │                       ││
│  │  • Manages deal type templates                 │                       ││
│  │  • Manages phase transitions                   │                       ││
│  │  • Routes events to correct phase workflow     │                       ││
│  │  • Creates/terminates Temporal Schedules        │                       ││
│  │  • Starts/completes phase workflows             │                       ││
│  └────────────────────────────────────────────────┼───────────────────────┘│
│                                                   │                        │
│                                                   ▼                        │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │                     TEMPORAL SERVER                                     ││
│  │                                                                        ││
│  │  PHASE WORKFLOWS (event_loop type)                                     ││
│  │  ┌──────────────────────────────────────────────────────────────────┐ ││
│  │  │  deal-abc:origination:1  ← processing document                  │ ││
│  │  │  deal-xyz:origination:1  ← waiting for events (zero compute)    │ ││
│  │  │  deal-pqr:amendment:2    ← waiting for approval                 │ ││
│  │  └──────────────────────────────────────────────────────────────────┘ ││
│  │                                                                        ││
│  │  SERVICING SCHEDULES (schedule_triggered type)                         ││
│  │  ┌──────────────────────────────────────────────────────────────────┐ ││
│  │  │  deal-abc: quarterly compliance (next: 2026-07-01)              │ ││
│  │  │  deal-abc: weekly position check (next: Monday 9am)             │ ││
│  │  │  deal-xyz: rate reset (on document: rate_notice)                │ ││
│  │  └──────────────────────────────────────────────────────────────────┘ ││
│  │                                                                        ││
│  │  MAIN LOOP (inside event_loop phase workflows):                        ││
│  │  ┌──────────────────────────────────────────────────────────────────┐ ││
│  │  │  1. Load template + fact ledger + working state                 │ ││
│  │  │  2. WAIT for events (zero compute)                              │ ││
│  │  │  3. CLASSIFY event → incremental / replacement / query          │ ││
│  │  │  4. EXTRACT: LLM reads documents, writes facts to ledger       │ ││
│  │  │  5. EVALUATE: deterministic rules check all gates               │ ││
│  │  │  6. ACT: execute triggered actions (with approval)              │ ││
│  │  │  7. Check completion_condition → hand off or loop               │ ││
│  │  └──────────────────────────────────────────────────────────────────┘ ││
│  │                                                                        ││
│  │  TASK QUEUE: "deal-agent-tasks"                                        ││
│  │  ┌──────────────────────────────────────────────────────────────────┐ ││
│  │  │  Worker Pool (stateless, autoscale) — any worker, any activity  │ ││
│  │  │  Each Activity checked by OPA before execution                   │ ││
│  │  └──────────────────────────────────────────────────────────────────┘ ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│           ┌──────────────────┼──────────────────┐                          │
│           ▼                  ▼                   ▼                          │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐                │
│  │ Layer A:      │  │ Layer B:          │  │ Layer C:       │               │
│  │ Raw Evidence  │  │ Fact Ledger       │  │ Working State  │               │
│  │              │  │                   │  │                │               │
│  │ OpenSearch   │  │ S3 + Trans. DB   │  │ S3 (agent      │               │
│  │ S3 (files)   │  │ (append-only,     │  │  memory)       │               │
│  │ BQL (events) │  │  provenance)      │  │                │               │
│  └──────────────┘  └──────────────────┘  └──────┬─────────┘               │
│                                                  │                          │
│                                        promotion (approved only)            │
│                                                  │                          │
│                                                  ▼                          │
│                                        ┌───────────────────┐               │
│                                        │ Layer D:           │               │
│                                        │ Committed Business │               │
│                                        │ State              │               │
│                                        │                    │               │
│                                        │ Transactional DB   │               │
│                                        │ (system of record) │               │
│                                        └───────────────────┘               │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  OPA POLICY ENGINE (deterministic bouncer)                             │ │
│  │  Tool allowlist → Context boundary → Data scope → Approval tier        │ │
│  │  No LLM reasoning. Human-edited YAML + engineer-written Rego.         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  OUTBOUND: Teams Bot                                                   │ │
│  │  Decision bundle approval cards + progress updates                     │ │
│  │  Approval responses → Signal back to phase workflow                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  AUDIT TRAIL (6 destinations)                                          │ │
│  │  S3 events.jsonl | S3 audit/decisions | Fact ledger history |          │ │
│  │  OPA decision log | Temporal history | Transactional DB outcomes       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Decision Bundle Approvals

### 7.1 Bundles, Not Individual Tool Calls

When a gate triggers an action, the workflow doesn't request approval for each tool call. Instead, it composes a **decision bundle** — a summary of what the agent proposes to do, with evidence.

```
Decision Bundle Example:
{
  "bundle_id": "db-a1b2c3",
  "context_id": "deal-abc-2026",
  "gate": "deal_structuring",
  "proposed_actions": [
    {
      "action": "create_deal_structures",
      "description": "Create three revolver structures based on extracted terms",
      "state_changes": [
        {"field": "facility_amount", "value": 250000000, "source": "credit_agreement_v2.pdf"},
        {"field": "facility_type", "value": "revolver", "source": "credit_agreement_v2.pdf"},
        {"field": "maturity_date", "value": "2028-03-15", "source": "credit_agreement_v2.pdf"}
      ],
      "destination": "transactional_db (Layer D)"
    }
  ],
  "evidence": {
    "source_documents": ["credit_agreement_v2.pdf", "term_sheet_final.pdf"],
    "fact_ids": ["f-a1b2c3", "f-d4e5f6", "f-g7h8i9"],
    "confidence_range": [0.92, 0.98]
  },
  "decision_context_snapshot": {
    "facts_at_time_of_proposal": [...],
    "snapshot_timestamp": "2026-03-22T14:30:00Z"
  },
  "approval_tier": "maker_checker",
  "approvers": ["j.smith", "m.jones"],
  "timeout": "24h",
  "escalation": "team_lead"
}
```

### 7.2 Stale Data Protection

When facts change while an approval is pending:

```
1. Agent posts decision bundle → Teams Adaptive Card
2. Workflow enters wait_condition (zero compute)
3. Meanwhile: new document arrives, changes facility_amount

   → Workflow wakes on new event
   → Extract phase processes new document
   → New fact written to ledger, old fact superseded
   → Evaluate phase detects: fact in decision_context_snapshot changed
   → Gate transitions: action_pending → paused
   → Workflow WITHDRAWS approval card from Teams
   → Posts message: "Approval withdrawn — facility_amount updated by new document"
   → Gate re-evaluates from scratch with new facts
   → If still satisfied: new decision bundle posted
   → If not: gate returns to unsatisfied
```

---

## 8. Context Configuration

### 8.1 Per-Deal Context (`context.yaml`)

With deal type templates, per-deal configuration is minimal:

```yaml
# Stored at: s3://agent-memory/{context_id}/context.yaml

context_id: deal-abc-2026
name: "Acme Corp Revolving Credit Facility 2026"
status: active
created_at: "2026-01-15T10:00:00Z"
created_by: "j.smith"

# --- Template Reference ---
template: revolving_credit_facility
template_version: "2.3"

# --- Current Phase ---
current_phase: origination
phase_instance: 1

# --- Source Mappings (deterministic context resolution) ---
sources:
  sharepoint:
    site: "sites/LoanOps"
    paths: ["/ABC-Revolver-2026/**", "/Acme-Corp/shared/**"]
  email:
    aliases: ["deal-abc@notices.internal.gs.com"]
    subject_patterns: [".*Acme.*compliance.*", ".*ABC.*rate.*notice.*"]
  lockbox:
    account_id: "LB-9942"
  clearpar:
    trade_ids: ["CP-2026-44821", "CP-2026-44822"]

# --- Per-Deal Overrides (optional) ---
# Override specific template values for this deal.
# Only fields listed here deviate from the template.
overrides:
  gates:
    kyc_initiation:
      timeout: 10d           # this deal needs more time for KYC
  approval_policy:
    single_approval:
      approvers: ["j.smith", "m.jones"]
    maker_checker:
      approvers: ["j.smith", "m.jones", "k.lee"]

# --- Outbound ---
outbound:
  teams:
    channel_id: "19:abc123@thread.tacv2/0"
    team_id: "team-loan-ops-2026"
```

---

## 9. Technology Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| **Orchestration** | Temporal (Python SDK) | Phase workflows + servicing schedules + Activities |
| **Agent Logic** | Python (existing codebase) | Workflow + Activity implementations |
| **Deal Type Templates** | YAML (S3-backed, versioned) | Business-maintained lifecycle definitions |
| **Gate Rule Engine** | Python (registered functions) | Deterministic evaluation, unit testable |
| **Channel Bridge** | Python + Power Automate | PA for SharePoint/Email triggers → webhook → Signal |
| **Policy Engine** | OPA (Rego + YAML data) | Deterministic bouncer. In-process → sidecar → centralized |
| **S3 Storage** | AWS S3 | Agent memory + fact ledger + raw artifacts + templates |
| **OpenSearch** | Existing cluster | Document indexing and search |
| **Transactional DB** | Postgres | Layer D committed state + context index + fact ledger queryable copy |
| **BQL** | Existing infrastructure | Read-only event stream |
| **Sandbox** | Docker containers / K8s Jobs | Calculator phase Python execution |
| **LLM** | Anthropic Claude | Extraction and reasoning only |
| **Outbound** | Teams Bot Framework | Decision bundle cards + Signals |

---

## 10. Implementation Phases

### Phase 1 — Foundation (Shadow Mode)

**Goal:** Single deal type, event loop workflow, extraction + gate evaluation. Agent observes and reports but does NOT write to Layer D.

- Temporal Workflow: `DealPhaseWorkflow` with signal handlers and main loop
- Deal type template: one template for revolving credit facility
- Fact ledger: S3-backed with provenance tracking
- Gate rule engine: `all_present_and_not_conflicted` rule implemented
- Activities: extraction, search, memory load/save
- OPA: in-process library with basic allowlist
- Shadow mode: agent posts what it *would* do to Teams, but doesn't execute write activities
- Single worker instance

**Validates:** Extraction quality, gate evaluation correctness, fact lifecycle, template model.

### Phase 2 — Channels, Approvals, and Write Access

**Goal:** Agent reacts to real events. Decision bundle approvals. Write access to Layer D.

- Channel Bridge: webhook endpoint + Power Automate integration
- SFTP watcher as Temporal Scheduled Workflow
- Dedupe pipeline: event ID + content hash
- Decision bundle approval cards in Teams
- Approval Signals back to workflow
- Stale data protection (approval withdrawal on fact change)
- Write Activities enabled (promotion from Layer C to Layer D)
- Conflict resolution: document precedence + version supersession
- Multiple workers (3-5)

**Validates:** Event-driven flow, approval UX, conflict handling, state promotion.

### Phase 3 — Phase Lifecycle and Servicing

**Goal:** Multi-phase deals. Schedule-triggered servicing.

- Phase transition: origination → servicing handoff
- Servicing Temporal Schedules (quarterly compliance, rate resets)
- Short-lived servicing workflows
- Amendment phase activation from servicing
- Document lineage tracking (draft → final → superseding)
- Additional deal type templates (term loan, delayed draw)
- Additional gate rules (`fresh`, `source_quality_above`)
- OPA moved to sidecar

**Validates:** Multi-phase lifecycle, long-term deal support, template extensibility.

### Phase 4 — Scale and Production

**Goal:** Production readiness. Multiple deal types. Full observability.

- Scale workers for production event volume
- BQL Consumer as Temporal Scheduled Workflow
- Cross-context dashboard querying transactional DB + Temporal Queries
- Observability: Temporal metrics + custom dashboards
- Template versioning and migration tooling
- Sandbox compute for Calculator phase
- Temporal Nexus for cross-context coordination (if needed)

**Validates:** Multi-tenancy, operational readiness, production monitoring.

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **Context ID** | Universal identifier scoping a deal. All events, documents, facts, and audit entries are scoped by context ID. |
| **Deal Type Template** | Versioned YAML configuration defining the lifecycle pattern (phases, gates, activities, schedules) for a category of deals. Business-maintained. |
| **Phase** | A bounded processing window within a deal's lifecycle. Event loop phases (origination, amendment) use persistent Temporal Workflows. Schedule-triggered phases (servicing) use short-lived workflows on Temporal Schedules. |
| **Fact Ledger** | Append-only store of extracted facts with full provenance (source, version, confidence, status, timestamps). Layer B of the state model. |
| **Fact Lifecycle** | observed → extracted → candidate → [conflicted →] approved → committed [→ superseded]. |
| **Readiness Gate** | A declarative condition in the deal type template. Specifies required fields, dependency gates, and a deterministic rule. When satisfied, triggers a configured activity with an approval tier. |
| **Gate Rule** | A deterministic function that evaluates fact ledger state against gate requirements. Not LLM-based. Unit testable. |
| **Decision Bundle** | A grouped set of proposed state changes submitted for human approval as a single unit. Includes evidence, source documents, and a snapshot of the facts at proposal time. |
| **Document Precedence** | Deterministic ordering of document types. When facts conflict, higher-precedence source wins. Defined per deal type template. |
| **Phase Transition** | Completion of one phase triggers the Context Registry to start the next phase. Origination → servicing. Servicing → amendment (on demand) → servicing. |
| **OPA Policy Engine** | Deterministic bouncer. Evaluates every Activity against allowlist, context boundary, data scope, and approval tier. No LLM reasoning. |
| **Promotion** | The act of moving approved facts from Layer C (working state) to Layer D (committed business state / system of record). Requires human approval. |
