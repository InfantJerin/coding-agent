# Deal Intelligence Agent Platform — System Architecture

## 1. Overview

### 1.1 Purpose

A context-scoped agentic platform that monitors business activity across an enterprise ecosystem — email, document repositories, application logs, transactional systems — and autonomously extracts information, detects discrepancies, runs computations, and takes action within defined approval boundaries.

Each **context** (a deal, a compliance review, a counterparty relationship) gets its own agent that:
- Observes events from multiple channels tagged with its context ID
- Reads and extracts terms from incoming documents
- Queries transactional systems for current state
- Runs calculations (risk, exposure, compliance checks)
- Communicates progress and requests approvals from humans
- Writes structured outcomes back to transactional systems

### 1.2 Design Principles

| # | Principle | Rationale |
|---|-----------|-----------|
| 1 | **File-based agent memory, tools for everything else** | Agent owns only its own state (S3 files). All business data accessed via scoped tools. Inspired by OpenClaw's simplicity — JSONL events, Markdown memory, JSON state. |
| 2 | **Context ID is the universal partition key** | Every event, document, memory file, tool call, and audit entry is tagged with a context ID. This is the boundary for isolation, access control, and data scoping. Temporal Workflow ID = context ID. |
| 3 | **Temporal-native lifecycle** | Each context is a long-lived Temporal Workflow. Events arrive as Signals. Tool calls execute as Activities on a shared worker pool. Approvals use `wait_condition()` with zero compute. |
| 4 | **Deny-by-default policy (OPA hybrid)** | Every Activity (tool call) evaluated by OPA. YAML defines per-context permissions (editable by compliance teams). Rego defines evaluation logic (written by engineers). |
| 5 | **Tiered approval gates** | Agent actions classified by risk level. Low-risk actions auto-proceed. High-risk actions require human approval via Teams Signals back to the Workflow. |
| 6 | **Separation of plumbing and intelligence** | Temporal handles orchestration, durability, retries, and scaling. The agent only handles reasoning (LLM calls). Channel Bridge handles event ingestion. |

### 1.3 Reference Architectures

| Source | What we adopt |
|--------|---------------|
| **OpenClaw** | File-based memory model (JSONL transcripts, Markdown memory). Channel adapter pattern. Tool policy pipeline. Session isolation per agent. |
| **NemoClaw / OpenShell** | Deny-by-default policy engine. Out-of-process enforcement. Four-level action evaluation. |
| **Temporal.io** | Workflow-per-context runtime. Signals for event delivery. Activities as tool calls. Worker pool scaling. Durable wait for approvals. continue-as-new for long-lived deals. |
| **OPA (Open Policy Agent)** | Hybrid policy model: YAML data (per-context permissions) + Rego logic (evaluation rules). Built-in decision logging and testing. Already adopted at GS (Cloud Entitlements). |
| **Existing agent_core** | Tool protocol, ToolRegistry, ToolPolicy, RunStrategy, DealStore, GenericHeadlessAgent, document extraction pipeline. |

---

## 2. System Architecture

### 2.1 Component Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                     DEAL INTELLIGENCE AGENT PLATFORM                          │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                        CHANNEL BRIDGE                                  │ │
│  │                                                                        │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────┐   │ │
│  │  │ Power        │ │ SFTP         │ │ BQL        │ │ Manual       │   │ │
│  │  │ Automate     │ │ Watcher      │ │ Consumer   │ │ Trigger      │   │ │
│  │  │              │ │              │ │            │ │ (API)        │   │ │
│  │  │ • SharePoint │ │ • Lockbox    │ │ • Fluent   │ │ • UI forms   │   │ │
│  │  │ • Email      │ │ • ClearPar   │ │   Bit apps │ │ • API calls  │   │ │
│  │  └──────┬───────┘ └──────┬───────┘ └─────┬──────┘ └──────┬───────┘   │ │
│  │         └────────────────┴───────────────┴────────────────┘           │ │
│  │                                  │                                    │ │
│  │                         resolve context_id                            │ │
│  │                         normalize event                               │ │
│  │                         send Signal to Temporal Workflow               │ │
│  └──────────────────────────────────┬─────────────────────────────────────┘ │
│                                     │ Temporal Signal                       │
│                                     ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      TEMPORAL SERVER                                  │   │
│  │                                                                       │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  DEAL AGENT WORKFLOWS (one per context_id)                     │  │   │
│  │  │                                                                │  │   │
│  │  │  Workflow: deal-abc-2026  ← waiting for events (zero compute)  │  │   │
│  │  │  Workflow: deal-xyz-2026  ← processing document (running)      │  │   │
│  │  │  Workflow: deal-pqr-2026  ← waiting for approval (zero compute)│  │   │
│  │  │  ...                                                           │  │   │
│  │  │                                                                │  │   │
│  │  │  Each workflow:                                                │  │   │
│  │  │  • Workflow ID = context_id (guarantees uniqueness)            │  │   │
│  │  │  • Receives events via Signals                                 │  │   │
│  │  │  • Executes tool calls as Activities                           │  │   │
│  │  │  • Waits for approvals via wait_condition (zero compute)       │  │   │
│  │  │  • Uses continue_as_new when history exceeds threshold         │  │   │
│  │  │  • Queryable: dashboard reads state without waking agent       │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                       │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  TASK QUEUE: "deal-agent-tasks"                                │  │   │
│  │  │                                                                │  │   │
│  │  │  Activities from ALL workflows route to this shared queue.     │  │   │
│  │  │  Worker pool consumes tasks. Temporal distributes work.        │  │   │
│  │  └─────────────────────────┬──────────────────────────────────────┘  │   │
│  └────────────────────────────┼──────────────────────────────────────────┘   │
│                               │                                              │
│              ┌────────────────┼────────────────┐                            │
│              ▼                ▼                 ▼                             │
│  ┌──────────────────┐ ┌────────────┐ ┌────────────┐                        │
│  │  Activity Worker  │ │  Worker 2  │ │  Worker N  │   (autoscale)         │
│  │                   │ │            │ │            │                        │
│  │  Stateless.       │ │  Same.     │ │  Same.     │                        │
│  │  Executes any     │ │            │ │            │                        │
│  │  Activity from    │ │            │ │            │                        │
│  │  any workflow.    │ │            │ │            │                        │
│  │                   │ │            │ │            │                        │
│  │  Each Activity    │ │            │ │            │                        │
│  │  passes through   │ │            │ │            │                        │
│  │  OPA Policy       │ │            │ │            │                        │
│  │  Engine before    │ │            │ │            │                        │
│  │  execution.       │ │            │ │            │                        │
│  └────────┬──────────┘ └─────┬──────┘ └─────┬──────┘                        │
│           │                  │              │                                │
│           └──────────────────┼──────────────┘                                │
│                              │                                               │
│          ┌───────────────────┼──────────────────────┐                       │
│          ▼                   ▼                       ▼                       │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────┐               │
│  │  S3           │   │ OpenSearch   │   │ Transactional DBs │               │
│  │  Agent Memory │   │ Doc Index    │   │                   │               │
│  │               │   │              │   │ • Positions       │               │
│  │  MEMORY.md    │   │ Indexed by   │   │ • Compliance      │               │
│  │  events.jsonl │   │ context_id   │   │ • Risk metrics    │               │
│  │  state.json   │   │              │   │ • CapEx           │               │
│  │  context.yaml │   │              │   │ • Deal status     │               │
│  │  audit/       │   │              │   │ • Context index   │               │
│  └──────────────┘   └──────────────┘   └───────────────────┘               │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  OPA POLICY ENGINE                                                    │   │
│  │                                                                       │   │
│  │  Hybrid: YAML data (per-context permissions) + Rego (eval logic)      │   │
│  │  Runs as sidecar or library. Evaluates every Activity before exec.    │   │
│  │                                                                       │   │
│  │  4 checks: Tool Allowlist → Context Boundary → Data Scope → Approval  │   │
│  │  Built-in decision logging for audit trail.                           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  OUTBOUND: Teams Bot                                                  │   │
│  │  Progress updates + Adaptive Cards for approvals                      │   │
│  │  Approval responses → Signal back to Temporal Workflow                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  BQL EVENT STREAM                                                     │   │
│  │  Fluent Bit agents on GS-managed applications ──► BQL                 │   │
│  │  Context ID tagged in application log lines                           │   │
│  │  Agent reads via Activity tool (read-only)                            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Temporal Primitives Mapping

| Platform concept | Temporal primitive | Behavior |
|-----------------|-------------------|----------|
| Context ID (deal-abc) | **Workflow ID** | One workflow execution per ID. Guarantees uniqueness and serialization. |
| Event arrives | **Signal** | Channel Bridge sends `on_event` Signal to workflow. Non-blocking, queued. |
| Agent wakes up | **Workflow resumes** | `wait_condition()` returns when signals arrive. Workflow continues execution. |
| Tool call | **Activity** | Each tool is a Temporal Activity. Runs on shared worker pool. Retryable. |
| Wait for approval | **wait_condition()** | Zero compute while waiting. Workflow is durable but not running. Can wait hours/days/weeks. |
| Approval arrives | **Signal** | Teams bot sends `on_approval_response` Signal. Workflow resumes. |
| Timeout + escalation | **Temporal Timer** | `workflow.sleep(timeout)` races against `wait_condition`. Survives crashes. |
| Worker pool | **Activity Workers** | N instances polling the Task Queue. Temporal distributes work. Scale by adding instances. |
| Context serialization | **Guaranteed** | One Workflow ID = one execution at a time. No two workers touch the same context. |
| Inspect deal status | **Query** | `workflow.query()` reads state without waking the agent. For dashboards. |
| Long-lived deal (months) | **continue_as_new()** | When event history exceeds threshold (~10K events), workflow restarts with carried-over state. |
| Scheduled checks | **Temporal Schedule** | Cron-style triggers (e.g., "check compliance every Monday"). Emits Signal to workflow. |
| Cross-context coordination | **Temporal Nexus** | Workflows signal each other across namespaces for portfolio-level operations. |

### 2.3 Data Flow — End to End

```
 ① EVENT ARRIVES
    Banker uploads compliance cert to SharePoint
         │
         ▼
 ② CHANNEL BRIDGE DETECTS
    Power Automate "file created" trigger fires
    → calls Channel Bridge webhook
    → Bridge resolves context_id from SharePoint folder path
    → Bridge indexes document content in OpenSearch (tagged with context_id)
    → Bridge sends Temporal Signal:
         temporal_client.get_workflow_handle("deal-abc-2026")
             .signal(DealAgentWorkflow.on_event, normalized_event)
         │
         ▼
 ③ WORKFLOW RESUMES
    DealAgentWorkflow for deal-abc-2026 was waiting (zero compute)
    Signal arrives → wait_condition() returns
    Workflow has pending_events list with the new event
         │
         ▼
 ④ WORKFLOW EXECUTES ACTIVITIES (tool calls on worker pool)
    a. execute_activity(load_agent_memory, context_id)     → Pull S3
    b. execute_activity(search_deal_documents, context_id)  → OpenSearch
    c. execute_activity(extract_terms, context_id, content) → LLM call
    d. execute_activity(get_compliance_status, context_id)  → Transactional DB
    e. Workflow logic compares extracted vs required
    f. Determines: "in compliance" or "discrepancy found"

    Each Activity passes through OPA Policy Engine before execution.
         │
         ▼
 ⑤ WORKFLOW DECIDES ACTION
    If straightforward (in compliance):
      → execute_activity(update_compliance_status, ...)   → Transactional DB
      → execute_activity(save_agent_memory, ...)          → S3
      → execute_activity(post_progress, ...)              → Teams
      → Workflow returns to wait_condition() (zero compute)

    If discrepancy or high-risk action:
      → execute_activity(post_approval_request, ...)      → Teams Adaptive Card
      → Workflow enters approval wait (see ⑥)
         │
         ▼
 ⑥ APPROVAL WAIT (if needed)
    Workflow calls:
      await workflow.wait_condition(
          lambda: approval_received,
          timeout=timedelta(hours=4)
      )
    Zero compute. Workflow is durable but not running.
    Can wait hours, days, or weeks.

    Banker sees Adaptive Card in Teams deal channel
    Clicks [Approve] / [Reject] / [Modify]
         │
         ▼
 ⑦ APPROVAL SIGNAL
    Teams bot receives Action.Execute callback
    Sends Signal to workflow:
      temporal_client.get_workflow_handle("deal-abc-2026")
          .signal(DealAgentWorkflow.on_approval_response, response)

    If timeout fires before approval:
      → execute_activity(escalate_approval, ...)  → Re-notify or escalate
      → Re-enter wait with new timeout
         │
         ▼
 ⑧ WORKFLOW RESUMES
    wait_condition returns with approval response
    Workflow executes approved action via Activities
    Updates S3 memory, transactional DB, Teams progress
    Returns to wait_condition() for next event
         │
         ▼
 ⑨ AUDIT TRAIL (automatic)
    Everything recorded:
      • S3 events.jsonl — what happened (agent perspective)
      • S3 audit/decisions.jsonl — what agent decided and why
      • Transactional DB — business outcomes
      • OPA decision log — every tool call evaluated (allow/deny)
      • Temporal event history — complete execution trace
```

---

## 3. Component Specifications

### 3.1 Channel Bridge

**Purpose:** Detect new content across external platforms, resolve context ID, publish normalized events as Temporal Signals.

#### 3.1.1 Inbound Channel Adapters

```
┌─────────────────────────────────────────────────────────────────────┐
│                     CHANNEL BRIDGE                                   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  POWER AUTOMATE ADAPTERS                                       │ │
│  │                                                                │ │
│  │  SharePoint:                                                   │ │
│  │    Trigger: "When a file is created or modified"               │ │
│  │    Detection: Microsoft Graph webhook + delta query            │ │
│  │    Context resolution: folder path mapping                     │ │
│  │    Output: HTTP POST to Channel Bridge webhook endpoint        │ │
│  │                                                                │ │
│  │  Email:                                                        │ │
│  │    Trigger: "When a new email arrives" (service mailbox)       │ │
│  │    Detection: Microsoft Graph webhook on mailbox               │ │
│  │    Context resolution: alias mapping or subject/sender parse   │ │
│  │    Output: HTTP POST to Channel Bridge webhook endpoint        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  CUSTOM ADAPTERS (Python)                                      │ │
│  │                                                                │ │
│  │  SFTP Watcher:                                                 │ │
│  │    Trigger: Temporal Schedule (every 15 min)                   │ │
│  │    Detection: List directory, compare against processed set    │ │
│  │    Sources: Lockbox (BAI2 files), ClearPar (trade packs)      │ │
│  │    Dedup: hash-based tracking of processed files               │ │
│  │                                                                │ │
│  │  BQL Consumer:                                                 │ │
│  │    Trigger: Temporal Schedule (poll interval)                  │ │
│  │    Detection: Query by context_id + time range                 │ │
│  │    Sources: All Fluent Bit-onboarded GS applications           │ │
│  │                                                                │ │
│  │  API Trigger:                                                  │ │
│  │    Trigger: HTTP endpoint for manual/programmatic events       │ │
│  │    Sources: UI form submissions, application callbacks         │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  CONTEXT ID RESOLVER                                           │ │
│  │                                                                │ │
│  │  Tier 1 — Preconfigured Mapping (handles ~80% of events)      │ │
│  │    SharePoint path → context_id   (from context.yaml)          │ │
│  │    Email alias → context_id       (from context.yaml)          │ │
│  │    Lockbox account → context_id   (from context.yaml)          │ │
│  │    ClearPar trade ID → context_id (from context.yaml)          │ │
│  │    BQL events → context_id        (already tagged)             │ │
│  │                                                                │ │
│  │  Tier 2 — Content Extraction (when path doesn't match)         │ │
│  │    Agent reads document, extracts identifiers:                 │ │
│  │    borrower name + agreement date + facility type              │ │
│  │    → matches against Context Registry                          │ │
│  │                                                                │ │
│  │  Tier 3 — Human Routing (when extraction fails)                │ │
│  │    Queued for human tagging via Teams/UI                       │ │
│  │    Human tags context_id → mapping saved for future            │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  SIGNAL DISPATCH                                               │ │
│  │                                                                │ │
│  │  After resolving context_id and normalizing the event:         │ │
│  │                                                                │ │
│  │  temporal_client.get_workflow_handle(context_id)                │ │
│  │      .signal(DealAgentWorkflow.on_event, normalized_event)     │ │
│  │                                                                │ │
│  │  If workflow doesn't exist yet (new context):                  │ │
│  │    → start_workflow(DealAgentWorkflow, id=context_id)          │ │
│  │    → then send Signal                                          │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.1.2 Normalized Event Format

Every event, regardless of source, is normalized to this structure before being sent as a Signal:

```json
{
  "event_id": "evt-a1b2c3d4",
  "context_id": "deal-abc-2026",
  "event_type": "document_received | app_event | manual_trigger | approval_response",
  "source": "sharepoint | email | lockbox | clearpar | bql | api | teams",
  "timestamp": "2026-03-22T14:30:00Z",
  "payload": {
    "document_ref": "sp://sites/LoanOps/ABC-Revolver/compliance_q1.pdf",
    "doc_type": "compliance_certificate",
    "metadata": { "uploader": "j.smith", "size_bytes": 245000 }
  },
  "resolution": {
    "method": "path_mapping | content_extraction | human_tagged",
    "confidence": 1.0
  }
}
```

---

### 3.2 Context Registry

**Purpose:** Central configuration store for all active contexts. Defines what the agent knows about its deal, where its data comes from, and what policies govern it.

#### 3.2.1 Context Configuration (`context.yaml`)

```yaml
# Stored at: s3://agent-memory/{context_id}/context.yaml

context_id: deal-abc-2026
name: "Acme Corp Revolving Credit Facility 2026"
status: active              # active | paused | closed
created_at: "2026-01-15T10:00:00Z"
created_by: "j.smith"

# --- Temporal Configuration ---
temporal:
  task_queue: "deal-agent-tasks"
  workflow_type: "DealAgentWorkflow"
  schedule:                          # optional scheduled triggers
    - cron: "0 9 * * MON"           # every Monday 9am
      event_type: "scheduled_compliance_check"

# --- Source Mappings (for context ID resolution) ---
sources:
  sharepoint:
    site: "sites/LoanOps"
    paths:
      - "/ABC-Revolver-2026/**"
      - "/Acme-Corp/shared/**"
  email:
    aliases:
      - "deal-abc@notices.internal.gs.com"
    subject_patterns:
      - ".*Acme.*compliance.*"
      - ".*ABC.*rate.*notice.*"
  lockbox:
    account_id: "LB-9942"
  clearpar:
    trade_ids: ["CP-2026-44821", "CP-2026-44822"]
  bql:
    context_filter: "context_id = 'deal-abc-2026'"

# --- Readiness Gates (field-level) ---
# Gates fire when ALL requires_fields are present in extracted_terms.
# Gates can depend on other gates via requires_gates (DAG — no cycles).
# On field conflict: last-write-wins, agent notifies user of overwrite.
readiness_gates:
  kyc_initiation:
    requires_fields:
      - entity_name
      - entity_type             # corporation, LLC, partnership
      - jurisdiction            # state/country of incorporation
      - beneficial_owners       # >25% owners
      - tax_id                  # EIN or equivalent
    triggers: initiate_kyc
    approval_tier: single_approval
    timeout: 5d
    on_timeout: escalate

  deal_structuring:
    requires_fields:
      - facility_amount
      - facility_type           # revolver, term loan, delayed draw
      - maturity_date
      - pricing_grid            # base rate + spread tiers
      - roles                   # agent, co-agent, participants
      - collateral_type
      - covenant_terms
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
    requires_gates: [deal_structuring]   # DAG — needs structures first
    triggers: calculate_roe_across_structures
    approval_tier: auto_approve          # computation only, no external action
    timeout: 1d
    on_timeout: notify

  quarterly_compliance:
    requires_fields:
      - compliance_certificate_received  # set true when doc arrives
      - positions_current                # set true when system data pulled
    timeout: 5d
    on_timeout: escalate

# --- Approval Policy (consumed by OPA as data) ---
approval_policy:
  auto_approve:
    - extract_terms
    - update_memory
    - post_progress
    - run_computation
    - search_documents

  single_approval:
    actions:
      - update_compliance_status
      - record_discrepancy
      - flag_for_review
    timeout: 4h
    escalation: deal_manager
    approvers: ["j.smith", "m.jones"]

  maker_checker:
    actions:
      - modify_deal_terms
      - update_positions
    timeout: 24h
    escalation: team_lead

  four_eyes:
    actions:
      - trigger_payment
      - settle_trade
    timeout: 48h
    escalation: department_head

# --- Tool Policy (consumed by OPA as data) ---
tool_policy:
  allow:
    - "search_deal_documents"
    - "get_positions"
    - "get_compliance_status"
    - "get_risk_metrics"
    - "get_capex_table"
    - "query_bql"
    - "update_compliance_status"
    - "record_discrepancy"
    - "run_python_sandbox"
    - "request_approval"
    - "post_progress"
  deny:
    - "trigger_payment"
    - "settle_trade"

# --- Outbound Channel ---
outbound:
  teams:
    channel_id: "19:abc123@thread.tacv2/0"
    team_id: "team-loan-ops-2026"
  email_digest:
    recipients: ["j.smith@gs.com", "m.jones@gs.com"]
    frequency: daily

# --- Agent Configuration ---
agent:
  model: "anthropic/claude-sonnet-4-6"
  max_turns_per_wake: 20
  strategy: "finance_deal"
  profile: "finance-docs"
```

#### 3.2.2 Context Registry Service

```
┌───────────────────────────────────────────────────────────────────┐
│  CONTEXT REGISTRY                                                  │
│                                                                    │
│  create_context(config) → context_id                               │
│    • Validates config                                              │
│    • Creates S3 directory structure                                │
│    • Registers source mappings                                     │
│    • Creates Teams channel (if enabled)                            │
│    • Writes row to context index (transactional DB)                │
│    • Starts Temporal Workflow:                                      │
│        temporal_client.start_workflow(                              │
│            DealAgentWorkflow.run,                                   │
│            args=[context_id],                                      │
│            id=context_id,                                          │
│            task_queue="deal-agent-tasks"                            │
│        )                                                           │
│    • Creates Temporal Schedules (if configured)                    │
│                                                                    │
│  resolve_context(source, path) → context_id | None                 │
│    • Checks preconfigured source mappings                          │
│    • Returns matching context_id or None                           │
│                                                                    │
│  get_context(context_id) → ContextConfig                           │
│    • Loads context.yaml from S3                                    │
│    • Returns parsed configuration                                  │
│                                                                    │
│  get_status(context_id) → dict                                     │
│    • Queries Temporal Workflow directly (no wake-up):               │
│        temporal_client.get_workflow_handle(context_id)              │
│            .query(DealAgentWorkflow.get_status)                     │
│                                                                    │
│  list_contexts(filter) → list[ContextSummary]                      │
│    • Queries transactional DB context index                        │
│    • Supports filtering by status, counterparty, etc               │
│                                                                    │
│  close_context(context_id)                                         │
│    • Sends close Signal to Temporal Workflow                       │
│    • Workflow archives memory and completes                        │
│    • Updates transactional DB index                                │
└───────────────────────────────────────────────────────────────────┘
```

---

### 3.3 Agent Runtime (Temporal Workflow + Activities)

**Purpose:** The core execution engine. Implemented as a Temporal Workflow (orchestration) and Activities (tool calls).

#### 3.3.1 Workflow Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    DEAL AGENT WORKFLOW                                 │
│                    (one per context_id)                                │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  SIGNAL HANDLERS (how events enter the workflow)               │  │
│  │                                                                │  │
│  │  on_event(event)              ← Channel Bridge sends events    │  │
│  │    → appends to pending_events list                            │  │
│  │                                                                │  │
│  │  on_approval_response(resp)   ← Teams bot sends approvals     │  │
│  │    → matches to pending_approval, stores response              │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  QUERY HANDLERS (read state without waking agent)              │  │
│  │                                                                │  │
│  │  get_status() → { pending_events, pending_approvals,           │  │
│  │                    workflow_position, last_activity }           │  │
│  │    ← Dashboard, admin tools query this directly                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  MAIN LOOP                                                     │  │
│  │                                                                │  │
│  │  1. Load config + memory (Activities: load_context_config,     │  │
│  │     load_agent_memory — includes extracted_terms.json)         │  │
│  │                                                                │  │
│  │  2. WAIT for events:                                           │  │
│  │     await workflow.wait_condition(                              │  │
│  │         lambda: len(pending_events) > 0                        │  │
│  │     )                                                          │  │
│  │     # ← ZERO COMPUTE. Can wait hours/days/weeks.              │  │
│  │                                                                │  │
│  │  3. PROCESS all pending events (batch):                        │  │
│  │     for event in pending_events:                               │  │
│  │       a. ANALYST: extract terms from document/email            │  │
│  │          → merge into extracted_terms (last-write-wins)        │  │
│  │          → if field overwritten: notify user of change         │  │
│  │          → each Activity checked by OPA Policy Engine          │  │
│  │                                                                │  │
│  │       b. OBSERVER: evaluate readiness gates                    │  │
│  │          for gate in unsatisfied_gates:                        │  │
│  │            missing = gate.requires_fields - extracted_terms    │  │
│  │            deps_met = all(gate.requires_gates) satisfied       │  │
│  │            if not missing AND deps_met:                        │  │
│  │              → mark gate SATISFIED                             │  │
│  │              → trigger gate.action (with approval tier)        │  │
│  │            else:                                               │  │
│  │              → log: "gate X: waiting on [missing], deps [...]" │  │
│  │                                                                │  │
│  │       c. CALCULATOR: if triggered by gate action               │  │
│  │          → execute sandboxed computation                       │  │
│  │                                                                │  │
│  │  4. SAVE memory (Activity: save_agent_memory                   │  │
│  │     — includes extracted_terms.json for external visibility)   │  │
│  │                                                                │  │
│  │  5. CHECK history size:                                        │  │
│  │     if history_length > 10000: continue_as_new(state)          │  │
│  │     # extracted_terms + gate_status carried across             │  │
│  │                                                                │  │
│  │  6. LOOP back to step 2                                        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  APPROVAL WAIT PATTERN                                         │  │
│  │                                                                │  │
│  │  # Post approval card to Teams                                 │  │
│  │  execute_activity(post_approval_request, channel, request)     │  │
│  │                                                                │  │
│  │  # Wait for response OR timeout                                │  │
│  │  try:                                                          │  │
│  │      await workflow.wait_condition(                             │  │
│  │          lambda: approval_response_received,                   │  │
│  │          timeout=timedelta(hours=4)  # from approval_policy    │  │
│  │      )                                                         │  │
│  │      # → Approved: execute action                              │  │
│  │      # → Rejected: log and continue                            │  │
│  │  except TimeoutError:                                          │  │
│  │      # → Escalate: re-notify or promote to next approver      │  │
│  │      execute_activity(escalate_approval, ...)                  │  │
│  │      # → Re-enter wait with new timeout                        │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

#### 3.3.2 Activities (Tool Calls on Worker Pool)

Each tool is a Temporal Activity. Activities run on the shared worker pool. Any worker can execute any Activity from any workflow.

**Read Activities** (query external systems):

| Activity | Source | Returns |
|----------|--------|---------|
| `search_deal_documents(context_id, query, doc_type?)` | OpenSearch | Matching document chunks |
| `get_positions(context_id)` | Transactional DB | Current positions |
| `get_compliance_status(context_id)` | Transactional DB | Compliance state |
| `get_risk_metrics(context_id)` | Transactional DB | Risk metrics |
| `get_capex_table(context_id)` | Transactional DB | CapEx data |
| `query_bql(context_id, time_range, event_type?)` | BQL | Application events |
| `load_agent_memory(context_id)` | S3 | MEMORY.md + state.json |
| `load_context_config(context_id)` | S3 | context.yaml |

**Write Activities** (mutate state, subject to OPA approval check):

| Activity | Target | OPA approval tier |
|----------|--------|-------------------|
| `update_compliance_status(context_id, status, evidence, as_of)` | Transactional DB | single_approval |
| `record_discrepancy(context_id, field, expected, actual, severity)` | Transactional DB | single_approval |
| `update_deal_terms(context_id, field, value, source_doc, evidence)` | Transactional DB | maker_checker |
| `record_computation_result(context_id, calc_type, result, inputs)` | Transactional DB | single_approval |
| `save_agent_memory(context_id, memory)` | S3 | auto_approve |

**Action Activities** (external effects):

| Activity | Target | Notes |
|----------|--------|-------|
| `post_progress(channel_id, message)` | Teams | Informational message |
| `post_approval_request(channel_id, request)` | Teams | Adaptive Card with buttons |
| `escalate_approval(config, request)` | Teams | Re-notify or escalate |
| `run_python_sandbox(context_id, code, input_data, timeout)` | Container | Sandboxed, no network |
| `extract_terms(context_id, content)` | LLM | Uses existing extraction pipeline |
| `index_document(context_id, doc_ref, content)` | OpenSearch | Index new document |

**Activity execution pattern:** Every Activity passes through OPA before execution.

```
Workflow schedules Activity
    │
    ▼
Worker picks up Activity from Task Queue
    │
    ▼
OPA Policy Engine evaluates:
  ├── Tool allowed? (context.yaml tool_policy)
  ├── Context boundary? (context_id matches)
  ├── Data scope? (S3 path, DB filter, OpenSearch filter)
  └── Approval required? (context.yaml approval_policy)
    │
    ├── DENIED → Activity returns PolicyDenied error → Workflow handles
    ├── APPROVAL_REQUIRED → Activity returns ApprovalNeeded → Workflow enters wait
    └── ALLOWED → Activity executes → result returned to Workflow
```

#### 3.3.3 Worker Pool

```
┌──────────────────────────────────────────────────────────────────────┐
│  ACTIVITY WORKER POOL                                                 │
│                                                                       │
│  All workers are IDENTICAL and STATELESS.                             │
│  Any worker can execute any Activity from any Workflow.               │
│  Context lives in S3 and Temporal, not in workers.                    │
│                                                                       │
│  async def run_worker():                                              │
│      client = await Client.connect("temporal-server:7233")            │
│      worker = Worker(                                                 │
│          client,                                                      │
│          task_queue="deal-agent-tasks",                                │
│          workflows=[DealAgentWorkflow],                                │
│          activities=[all_activity_functions],                          │
│          max_concurrent_activities=10,     # per worker instance       │
│          max_concurrent_workflow_tasks=5,  # per worker instance       │
│      )                                                                │
│      await worker.run()                                               │
│                                                                       │
│  Scaling:                                                             │
│  ─────────────────────────────────────────────────                    │
│  Low load  (50 deals, ~10 events/hr)   → 2-3 workers                 │
│  Medium    (200 deals, ~100 events/hr) → 5-10 workers                │
│  High load (500 deals, ~500 events/hr) → 20-50 workers               │
│                                                                       │
│  Scale by event volume, NOT by deal count.                            │
│  500 idle deals = 0 worker load.                                      │
│  5 busy deals = same load as 500 busy deals with same event volume.   │
└──────────────────────────────────────────────────────────────────────┘
```

#### 3.3.4 Agent Roles

The workflow determines which role to activate based on the event type:

**Analyst** — Document reading and term extraction (runs first on document events)
```
Trigger: document_received or email_received event
Does:    • Fetches document content via OpenSearch
         • Extracts terms (existing extraction pipeline)
         • Merges into extracted_terms (last-write-wins per field)
         • If field value changed: logs old → new, notifies user
           (no approval before overwrite — user can ask agent to revert)
         • Compares extracted terms against transactional system data
         • Detects discrepancies
         • Updates deal memory
Tools:   search_deal_documents, get_positions, get_compliance_status,
         update_compliance_status, record_discrepancy, request_approval
```

**Observer** — Gate evaluation and action triggering (runs after every extraction)
```
Trigger: After Analyst completes extraction (every event cycle)
Does:    • Evaluates ALL unsatisfied readiness gates against extracted_terms
         • For each gate: checks requires_fields present + requires_gates met
         • When gate satisfied: triggers the gate's action
           (e.g., kyc_initiation → initiate_kyc, deal_structuring → create_deal_structures)
         • When gate not satisfied: logs what's missing, posts progress
         • Correlates events across sources for milestone detection
Tools:   query_bql, post_progress, initiate_kyc, create_deal_structures,
         calculate_roe_across_structures (read-heavy + trigger actions)
```

**Calculator** — Computation execution (triggered by gate actions like ROE)
```
Trigger: Gate action requires computation (e.g., calculate_roe_across_structures)
Does:    • Pulls data tables from transactional systems
         • Generates or selects Python code
         • Executes in sandboxed container
         • Returns results — may produce multiple structures for comparison
         • Results written to transactional DB for downstream use
Tools:   get_capex_table, run_python_sandbox
```

#### 3.3.5 Agent Memory Files (S3)

```
s3://agent-memory/{context_id}/
│
├── context.yaml              # Deal configuration (Section 3.2.1)
│
├── MEMORY.md                 # Agent's living understanding
│   │                         # Read by workflow on every wake-up (via Activity)
│   │                         # Updated after every significant action
│   │                         # Human-readable, LLM-native format
│   │
│   │  ┌─────────────────────────────────────────────────┐
│   │  │ # Deal ABC — Acme Corp Revolving Credit          │
│   │  │                                                   │
│   │  │ ## Current Status                                 │
│   │  │ - Facility: $50M, SOFR+200bps                    │
│   │  │ - Compliance: In compliance (Q1 2026)            │
│   │  │                                                   │
│   │  │ ## Key Terms                                      │
│   │  │ - Maturity: March 2028                           │
│   │  │ - Covenants: Leverage ≤ 3.5x, Coverage ≥ 2.0x   │
│   │  │                                                   │
│   │  │ ## Recent Activity                                │
│   │  │ - [2026-03-10] Rate notice: SOFR+250bps          │
│   │  │ - [2026-03-10] ⚠ Discrepancy: +50bps vs agree   │
│   │  │                                                   │
│   │  │ ## Open Items                                     │
│   │  │ - [ ] Rate discrepancy pending review             │
│   │  │ - [ ] Q2 compliance cert due July 15              │
│   │  └─────────────────────────────────────────────────┘
│
├── extracted_terms.json      # Accumulated fields extracted from documents
│                             # Primary copy lives in workflow state (fast)
│                             # S3 copy written on save for external visibility
│                             #
│                             # Example:
│                             # {
│                             #   "entity_name": {
│                             #     "value": "Acme Corp",
│                             #     "source": "credit_agreement_v2.pdf",
│                             #     "extracted_at": "2026-03-20T14:30:00Z",
│                             #     "previous": {           ← only if overwritten
│                             #       "value": "Acme Corporation",
│                             #       "source": "term_sheet_draft.pdf"
│                             #     }
│                             #   },
│                             #   "facility_amount": {
│                             #     "value": 250000000,
│                             #     "source": "credit_agreement_v2.pdf",
│                             #     "extracted_at": "2026-03-20T14:30:00Z"
│                             #   }
│                             # }
│
├── gate_status.json          # Which gates are satisfied, when, what triggered them
│                             # Written alongside extracted_terms.json
│
├── events.jsonl              # Append-only event log (agent perspective)
│                             # One JSON per line, never edited
│
├── state.json                # Current workflow state (for continue_as_new)
│                             # Rebuildable from events.jsonl
│
└── audit/
    └── decisions.jsonl       # Agent decisions with reasoning (append-only)
```

---

### 3.4 Storage Architecture

#### 3.4.1 Four-Tier Storage Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          STORAGE TIERS                                   │
│                                                                          │
│  TIER 1: S3 — Agent Memory                                              │
│  ─────────────────────────────                                          │
│  What: Agent's own state — MEMORY.md, extracted_terms.json,              │
│        gate_status.json, events.jsonl, state.json, context.yaml,        │
│        audit/decisions.jsonl                                             │
│  Who writes: Agent via Activities, Channel Bridge (events)               │
│  Who reads: Agent only (private to this context's workflow)             │
│  Partitioned by: context_id (one S3 prefix per context)                 │
│  Why S3: Stateless workers need durable external storage.               │
│          Files are the simplest interface. Activity pulls on wake,       │
│          pushes on save. No connection pools, no schema migrations.     │
│                                                                          │
│  TIER 2: OpenSearch — Document Index                                     │
│  ─────────────────────────────────────                                  │
│  What: Extracted document content, chunked and indexed for search        │
│  Who writes: Channel Bridge (on document ingestion)                     │
│  Who reads: Agent (via search_deal_documents Activity)                  │
│  Partitioned by: context_id field on every indexed document             │
│  Why OpenSearch: Existing pattern in the org.                           │
│                                                                          │
│  TIER 3: Transactional DB — Business State                              │
│  ─────────────────────────────────────────                              │
│  What: Live business data (positions, compliance, risk, CapEx)          │
│        AND agent-produced business outcomes (extracted terms,            │
│        discrepancies, computation results, deal status)                  │
│        AND context index (for cross-context queries by dashboards)      │
│  Who writes: Source applications + Agent (via write Activities)          │
│  Who reads: Agent, dashboards, reports, other systems                   │
│  Partitioned by: context_id / deal_id in application schema            │
│  Why DB: Business facts queryable by many consumers. Cross-context      │
│          queries live here. System of record.                            │
│                                                                          │
│  TIER 4: BQL — Application Event Stream                                 │
│  ──────────────────────────────────────                                 │
│  What: Structured logs from GS-managed applications via Fluent Bit     │
│  Who writes: Applications (via Fluent Bit)                              │
│  Who reads: Agent (via query_bql Activity), read-only                   │
│  Partitioned by: context_id tagged in application log lines             │
│  Why BQL: Existing infrastructure.                                      │
│                                                                          │
│  TIER 5: Temporal — Workflow Execution State                            │
│  ────────────────────────────────────────────                           │
│  What: Workflow event history, pending signals, timer state             │
│  Who writes: Temporal Server (automatic)                                │
│  Who reads: Temporal Server, Dashboard (via Query)                      │
│  Why: Temporal maintains its own execution state. This is the           │
│       durability layer — survives crashes, restarts, deployments.       │
│       Complementary to S3 (agent memory) and DB (business state).      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 3.4.2 Responsibility Matrix

```
┌────────────────────────────┬────────┬──────────┬──────────┬──────┬──────────┐
│ Data                       │ S3     │OpenSearch │Trans. DB │ BQL  │ Temporal  │
│                            │(Tier 1)│(Tier 2)  │(Tier 3)  │(T 4) │ (Tier 5) │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Agent memory (MEMORY.md)   │write/  │          │          │      │          │
│                            │read    │          │          │      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Agent event log            │append/ │          │          │      │          │
│                            │read    │          │          │      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Agent audit decisions      │append/ │          │          │      │          │
│                            │read    │          │          │      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Deal configuration         │write/  │          │          │      │          │
│                            │read    │          │          │      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Document content (indexed) │        │write/read│          │      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Business state (compliance,│        │          │write/read│      │          │
│ positions, risk, terms)    │        │          │          │      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Context index (cross-ctx)  │        │          │write/read│      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Application event logs     │        │          │          │ read │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Workflow execution state   │        │          │          │      │ automatic│
│ (signals, timers, history) │        │          │          │      │          │
├────────────────────────────┼────────┼──────────┼──────────┼──────┼──────────┤
│ Pending approvals + state  │        │          │          │      │ in-wf    │
│                            │        │          │          │      │ state    │
└────────────────────────────┴────────┴──────────┴──────────┴──────┴──────────┘

Legend:
  write = creates or updates    read = queries
  append = append-only writes   automatic = managed by Temporal
  in-wf state = held in workflow variables (durable via Temporal)
```

---

### 3.5 Approval Gateway (Temporal-native)

**Purpose:** Route agent actions through human approval flows. Implemented as a pattern within the Temporal Workflow, not a separate service.

With Temporal, the Approval Gateway is not a standalone component — it's a **pattern within the workflow**: post card (Activity) → wait_condition (zero compute) → resume on Signal or timeout.

#### 3.5.1 Approval Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  APPROVAL FLOW (inside Temporal Workflow)                              │
│                                                                       │
│  1. OPA determines action needs approval                              │
│     (tool_policy + approval_policy from context.yaml)                 │
│                                                                       │
│  2. CLASSIFY risk tier:                                               │
│     auto_approve ─────► Execute Activity immediately                  │
│     single_approval ──► Post card, wait for 1 Signal                  │
│     maker_checker ────► Post card, wait for 2 Signals                 │
│     four_eyes ────────► Post card, wait for 2 independent Signals     │
│                                                                       │
│  3. POST approval request (Activity):                                 │
│     execute_activity(post_approval_request, channel_id, {             │
│         action, reasoning, evidence, diff_view, approvers             │
│     })                                                                │
│     → Adaptive Card posted to deal's Teams channel                    │
│                                                                       │
│  4. WAIT (zero compute, survives crashes):                            │
│     try:                                                              │
│         await workflow.wait_condition(                                 │
│             lambda: approval_received(request_id),                    │
│             timeout=policy_timeout   # e.g., 4h / 24h / 48h          │
│         )                                                             │
│     except TimeoutError:                                              │
│         → execute_activity(escalate_approval, ...)                    │
│         → Re-enter wait with escalated approvers                      │
│                                                                       │
│  5. RESUME on Signal:                                                 │
│     on_approval_response Signal arrives from Teams bot                │
│     wait_condition returns                                            │
│     Workflow reads response: approved / rejected / modified           │
│     Proceeds accordingly                                              │
│                                                                       │
│  Temporal provides for free:                                          │
│  • Durable wait (survives server restarts)                            │
│  • Configurable timeout (from approval_policy)                        │
│  • Zero compute while waiting                                         │
│  • Audit trail (Temporal event history logs every Signal + Activity)  │
└──────────────────────────────────────────────────────────────────────┘
```

#### 3.5.2 Outbound Channel Abstraction

```
Protocol:
  send_approval_request(channel, request) → request_id
  send_progress_update(channel, message)

Implementations:
  ┌──────────────────────────────────────────────────────────┐
  │  TeamsChannel                                             │
  │  • Posts Adaptive Cards with action buttons               │
  │  • Receives Action.Execute callbacks via Bot Framework    │
  │  • Bot sends Signal to Temporal Workflow on callback      │
  │  • User-specific views (only approvers see buttons)       │
  └──────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────┐
  │  EmailChannel (fallback)                                  │
  │  • Sends email with approval link → web UI                │
  │  • Web UI sends Signal to Temporal Workflow on action     │
  └──────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────┐
  │  WebUIChannel (future)                                    │
  │  • Dedicated approval dashboard                           │
  │  • Queries all workflows for pending approvals            │
  │  • Sends Signals on approval actions                      │
  └──────────────────────────────────────────────────────────┘
```

#### 3.5.3 Notification Types

| Type | Content | Channel | Interaction |
|------|---------|---------|-------------|
| **Progress update** | "Processed Q1 compliance cert. Deal ABC in compliance." | Teams message | None (informational) |
| **Approval request** | Action + reasoning + evidence + diff + buttons | Teams Adaptive Card | Approve / Reject / Modify → Signal |
| **Escalation** | "Approval pending for 4h. Escalating to [manager]." | Teams message + @ mention | Same as approval → Signal |
| **Alert** | "Discrepancy detected: rate +50bps above agreement." | Teams message (urgent) | Optional: link to review |
| **Daily digest** | Summary of all agent activity across deals | Email | None (informational) |

---

### 3.6 Policy Engine (OPA Hybrid)

**Purpose:** Enforce deny-by-default access control on every Activity execution. Ensure agents only access their own context's data. Audit every decision.

#### 3.6.1 Hybrid Architecture: YAML Data + Rego Logic

```
┌──────────────────────────────────────────────────────────────────────┐
│  OPA POLICY ENGINE                                                    │
│                                                                       │
│  YAML (per-context, edited by compliance/deal teams):                 │
│    context.yaml → tool_policy (allow/deny lists)                      │
│    context.yaml → approval_policy (tiers, approvers, timeouts)        │
│    Loaded as OPA data: data.contexts[context_id]                      │
│                                                                       │
│  Rego (written once by engineers, tested, versioned):                 │
│    policy.rego → evaluation logic (4 checks)                          │
│    Tested with: opa test --coverage                                   │
│    Deployed via: OPA bundle (signed, atomic update)                   │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  EVALUATION PIPELINE (runs on every Activity)                  │  │
│  │                                                                │  │
│  │  Input:                                                        │  │
│  │  {                                                             │  │
│  │    "tool_name": "update_compliance_status",                    │  │
│  │    "agent_context_id": "deal-abc-2026",                        │  │
│  │    "tool_args": { "context_id": "deal-abc-2026", ... }         │  │
│  │  }                                                             │  │
│  │                                                                │  │
│  │  Check 1: TOOL ALLOWED                                         │  │
│  │    Is tool_name in data.contexts[context_id].tool_policy.allow │  │
│  │    AND NOT in deny list?                                       │  │
│  │    DENY if not explicitly allowed.                             │  │
│  │                                                                │  │
│  │  Check 2: CONTEXT BOUNDARY                                     │  │
│  │    Does tool_args.context_id == agent_context_id?              │  │
│  │    Cross-context access DENIED.                                │  │
│  │                                                                │  │
│  │  Check 3: DATA SCOPE                                           │  │
│  │    S3 path must be under s3://agent-memory/{context_id}/       │  │
│  │    DB queries must include context_id filter.                  │  │
│  │    OpenSearch queries must include context_id filter.          │  │
│  │                                                                │  │
│  │  Check 4: APPROVAL TIER                                        │  │
│  │    What tier does this action require?                         │  │
│  │    auto_approve → proceed                                      │  │
│  │    single_approval / maker_checker / four_eyes → return tier   │  │
│  │                                                                │  │
│  │  Output:                                                       │  │
│  │  {                                                             │  │
│  │    "allow": true,                                              │  │
│  │    "approval_required": "single_approval",                     │  │
│  │    "approvers": ["j.smith", "m.jones"],                        │  │
│  │    "reason": "tool allowed, approval required per policy"      │  │
│  │  }                                                             │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  DECISION LOG (OPA built-in)                                   │  │
│  │                                                                │  │
│  │  Every evaluation automatically logged:                        │  │
│  │  {                                                             │  │
│  │    "decision_id": "d-123",                                     │  │
│  │    "timestamp": "2026-03-22T14:30:00Z",                        │  │
│  │    "input": { tool_name, context_id, args_hash },              │  │
│  │    "result": { allow, approval_required, reason },             │  │
│  │    "policy_version": "v2.3.1",                                 │  │
│  │    "latency_ms": 0.3                                           │  │
│  │  }                                                             │  │
│  │  → Written to audit/decisions.jsonl in S3                      │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  SANDBOX POLICY (for Calculator role)                          │  │
│  │                                                                │  │
│  │  When tool = run_python_sandbox:                               │  │
│  │    • Spin up isolated container                                │  │
│  │    • Mount: input data only (read-only)                        │  │
│  │    • Network: NONE                                             │  │
│  │    • Packages: pre-approved set (numpy, pandas, scipy)         │  │
│  │    • Timeout: configurable per context (default 5 min)         │  │
│  │    • Memory limit: configurable (default 2GB)                  │  │
│  │    • Output: stdout + result file only                         │  │
│  │    • Code + input + output logged for reproducibility          │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  Deployment progression:                                              │
│    Phase 1: OPA as Python library (in-process, simplest)              │
│    Phase 2: OPA as sidecar (out-of-process, agent can't tamper)       │
│    Phase 3: Centralized OPA server (shared across all workers,        │
│             managed via Styra DAS or internal bundle server)           │
│                                                                       │
│  Note: OPA already adopted at GS (Cloud Entitlements Service).        │
│  Check internally for existing OPA infrastructure to leverage.        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Mapping to Existing Codebase

### 4.1 What Extends

| Existing Module | Becomes | Changes Needed |
|----------------|---------|----------------|
| `agent_core/runner.py` — `GenericHeadlessAgent` | **Temporal Activities** (Analyst role logic) | Extraction pipeline reused as Activity implementations. Workflow orchestrates the sequence. |
| `agent_core/session.py` — `DealStore` | **Context Registry** | Extend with S3 backend, context.yaml schema, Temporal workflow lifecycle. |
| `agent_core/session.py` — `SessionStore` | **Replaced by Temporal + S3** | Workflow state in Temporal. Agent memory in S3. No separate session store. |
| `agent_core/tooling.py` — `ToolRegistry` | **Activity Registry** | Same protocol. Each tool becomes a Temporal Activity function. |
| `agent_core/tooling.py` — `ToolPolicy` | **OPA Policy Engine** | Replace Python policy with OPA hybrid. YAML data from context.yaml. Rego evaluation logic. |
| `agent_core/strategy.py` — `RunStrategy` | **Workflow logic + readiness gates** | Strategy becomes workflow control flow. Gates use `wait_condition`. |
| `agent_core/models.py` — `TaskRequest` | **Normalized Event** | TaskRequest becomes one event type. Events are Temporal Signal payloads. |
| `agent_core/memory.py` — `MemoryStore` | **MEMORY.md** (S3 file) | Replace token-based retrieval with Markdown file. Loaded/saved as Activities. |
| `tools/document_tools.py` | **Analyst Activities** | Reuse extraction pipeline. Add OpenSearch adapter. |
| `tools/finance_tools.py` | **Analyst Activities** | Reuse extraction schemas. Write results to transactional DB via Activities. |
| `tools/retrieval_tools.py` | **OpenSearch Activity** | Replace local BM25 with OpenSearch queries scoped by context_id. |
| `tools/excel_tools.py` | **Calculator Activities** | Table extraction + Python execution as sandboxed Activity. |
| `profiles/finance_docs.py` | **Agent profile** | Same concept. Profile configures which Activities + policies for finance deals. |
| `schemas/finance/` | **Extraction schemas** | Reused as-is. |

### 4.2 What's New

| New Component | Purpose |
|---------------|---------|
| `workflows/deal_agent.py` | Temporal Workflow: main loop, signal handlers, approval pattern |
| `activities/` | All Activity implementations (tools as Temporal Activities) |
| `workers/` | Worker setup and configuration |
| `channel_bridge/` | Webhook endpoint, SFTP watcher, BQL consumer, Signal dispatch |
| `context_registry/` | Context CRUD, S3 ops, Temporal workflow lifecycle |
| `policy/` | OPA integration: Rego policies, YAML loading, decision logging |
| `policy/policies/agent.rego` | Rego evaluation logic (4-check pipeline) |
| `activities/transactional.py` | Read/write Activities for transactional DB |
| `activities/opensearch.py` | Document search Activity |
| `activities/bql.py` | BQL query Activity |
| `activities/teams.py` | Post progress, post approval card, escalate |
| `activities/sandbox.py` | Container-sandboxed Python execution |
| `activities/s3_memory.py` | Load/save agent memory from S3 |

---

## 5. Open Questions

### 5.1 Requires Internal Validation

| # | Question | Team to Ask | Impact if Blocked | Fallback |
|---|----------|-------------|-------------------|----------|
| 1 | **Temporal availability** — which Temporal deployment exists? Self-hosted or Temporal Cloud? Namespace allocation? | Infra / platform team | This is foundational — if no Temporal, fall back to custom queue + workers | SQS FIFO + ECS Tasks |
| 2 | **Teams Bot Framework** — is it available? Can we deploy a bot for Adaptive Card callbacks that send Temporal Signals? | GS Microsoft team | Cannot do interactive approvals in Teams | Email with links to web UI → web UI sends Temporal Signals |
| 3 | **Programmatic Teams channel creation** — status of division POC? | Division team | Manual channel provisioning at deal creation | Pre-created channels |
| 4 | **Power Automate** — can flows call external webhook endpoints? | IT / platform team | Build custom Graph API adapters | Python adapter with Graph delta queries on Temporal Schedule |
| 5 | **BQL capabilities** — queryable by external services? API? | BQL platform team | Determines BQL Consumer Activity implementation | Read Fluent Bit output directly |
| 6 | **Container runtime** — K8s, ECS? For sandbox execution + Temporal worker deployment. | Infra / platform team | Determines sandbox + worker deployment | Subprocess sandbox (weaker isolation) |
| 7 | **S3 access** — available for agent memory? | Cloud / storage team | Use alternative durable storage | NFS, Azure Blob, internal object store |
| 8 | **Transactional DB** — which DB for agent-produced business outcomes? | Data architecture team | Determines write Activity implementations | Start with existing deal DB |
| 9 | **OpenSearch** — can we create new indexes? | Search platform team | Fall back to local BM25 | Existing retrieval_tools.py |
| 10 | **OPA at GS** — is there an existing OPA platform (Cloud Entitlements)? Can we leverage it? | Security / platform team | Stand up own OPA instance | OPA as in-process library |

### 5.2 Architecture Decisions Resolved

| # | Decision | Resolution |
|---|----------|-----------|
| 1 | **Agent runtime model** | Temporal: one Workflow per context, shared Activity Worker pool. Scale workers by event volume. |
| 2 | **Event queue** | Temporal Signals (no separate SQS/Kafka needed). |
| 3 | **Policy engine** | OPA hybrid: YAML data (per-context) + Rego logic (shared). Deploy as library → sidecar → centralized. |
| 4 | **Approval mechanism** | Temporal wait_condition + Signals. Teams Adaptive Cards for UI. |
| 5 | **State durability** | Temporal for workflow state. S3 for agent memory. Transactional DB for business outcomes. |
| 6 | **Scaling model** | Worker pool scales by event volume, not by deal count. |

### 5.3 Architecture Decisions Still Open

| # | Decision | Options | Recommendation | Depends On |
|---|----------|---------|----------------|------------|
| 1 | Cross-context intelligence | Workflow queries transactional DB vs. Temporal Nexus for portfolio agent | Start with DB queries; add Nexus later | Temporal Nexus availability |
| 2 | LLM-generated vs pre-approved Python | Calculator runs agent-written code vs. parameterized templates | Start with templates, graduate to generated | Sandbox strength (#6 above) |
| 3 | Outbound channel priority | Teams-first vs. web UI-first | Teams-first (where bankers work) | Teams Bot availability (#2 above) |
| 4 | BQL integration direction | Read-only vs. agent writes back | Read-only to start | BQL capabilities (#5 above) |

---

## 6. Implementation Phases

### Phase 1 — Foundation

**Goal:** Single-context agent as a Temporal Workflow. Manual trigger. Local transactional store. S3-backed memory.

- Temporal Workflow: `DealAgentWorkflow` with signal handlers and main loop
- Activities: `load_agent_memory`, `save_agent_memory`, existing extraction tools
- Context Registry: S3-backed context.yaml, Workflow lifecycle management
- MEMORY.md + events.jsonl + state.json persistence via S3 Activities
- Local transactional DB (SQLite or Postgres) with read/write Activities
- OPA as in-process library with basic Rego policies
- Manual trigger: start Workflow, send Signal via CLI/API
- Worker: single instance with Workflow + Activity runners

**Validates:** Temporal Workflow lifecycle, Activity execution, memory model, OPA integration.

### Phase 2 — Channels and Approval

**Goal:** Agent reacts to real events. Communicates with humans via Teams.

- Channel Bridge: webhook endpoint receiving Power Automate calls, sends Temporal Signals
- SFTP watcher as Temporal Scheduled Workflow
- Context ID resolver (preconfigured mapping)
- Approval pattern: `wait_condition` + Temporal Signals from Teams bot
- Tiered approval policy evaluated by OPA
- Escalation via Temporal timers
- Multiple workers (scale to 3-5)

**Validates:** Event-driven Signals, channel adapters, human-in-the-loop with Temporal.

### Phase 3 — Sandbox and Computation

**Goal:** Agent runs calculations in isolated containers.

- Sandboxed container execution as Activity (`run_python_sandbox`)
- Container policy: no network, read-only data mount, timeout, memory limit
- Pre-approved Python templates + parameterized execution
- Computation results written to transactional DB via approved Activity
- OPA sandbox policy enforcement

**Validates:** Sandbox isolation, computation pipeline, data scoping.

### Phase 4 — Scale and Observability

**Goal:** Production readiness. Multiple contexts. Monitoring.

- Scale workers to handle production event volume
- BQL Consumer as Temporal Scheduled Workflow
- Cross-context dashboard querying transactional DB + Temporal Workflow Queries
- Observability: Temporal metrics + custom dashboards
- OPA moved to sidecar (out-of-process isolation)
- continue_as_new for long-running deal workflows
- Temporal Nexus for cross-context coordination (if needed)

**Validates:** Multi-tenancy, operational readiness, production monitoring.

---

## Appendix A: Technology Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| **Orchestration** | Temporal (Python SDK) | Workflows + Activities. Core runtime. |
| **Agent Logic** | Python (existing codebase) | Workflow + Activity implementations |
| **Channel Bridge** | Python + Power Automate | PA for SharePoint/Email triggers → webhook → Signal |
| **Policy Engine** | OPA (Rego + YAML data) | In-process library → sidecar → centralized |
| **S3 Storage** | AWS S3 or equivalent | Agent memory files |
| **OpenSearch** | Existing cluster | Document indexing and search |
| **Transactional DB** | Postgres or existing deal database | Business state + agent outcomes + context index |
| **BQL** | Existing infrastructure | Read-only event stream |
| **Sandbox** | Docker containers / K8s Jobs | Calculator role Python execution |
| **LLM** | Anthropic Claude or OpenAI | Existing provider adapters |
| **Outbound** | Teams Bot Framework (or Power Automate fallback) | Adaptive Cards + Signals |

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Context ID** | Universal identifier scoping a boundary of related activity — typically a deal. Maps to Temporal Workflow ID. All events, documents, memory, tool access, and audit entries are scoped by context ID. |
| **Temporal Workflow** | A long-lived, durable execution representing one deal context. Receives events via Signals, executes tool calls as Activities, waits for approvals with zero compute, and survives crashes/restarts. |
| **Temporal Activity** | A single tool call executed on the shared worker pool. Each Activity is checked by OPA before execution. Retryable, with configurable timeouts. |
| **Temporal Signal** | An asynchronous message sent to a Workflow from outside (Channel Bridge, Teams bot, API). Used to deliver events and approval responses. |
| **Temporal Query** | A read-only inspection of Workflow state. Used by dashboards to check deal status without waking the agent. |
| **Channel Bridge** | Infrastructure layer that detects new content, resolves context ID, and sends Temporal Signals to the appropriate Workflow. |
| **Context Registry** | Configuration store mapping context IDs to sources, policies, and Temporal Workflows. Stored as context.yaml in S3 with an index in the transactional DB. |
| **Agent Memory** | The agent's private state in S3 — MEMORY.md, extracted_terms.json, gate_status.json, events.jsonl, state.json, audit/decisions.jsonl. Loaded/saved as Temporal Activities. |
| **Extracted Terms** | Accumulated field values extracted from documents across the deal lifecycle. Stored in `extracted_terms.json`. Primary copy in workflow state (fast, durable); S3 copy for external visibility. Last-write-wins on conflict, with previous value retained and user notified. |
| **OPA Policy Engine** | Open Policy Agent evaluating every Activity. Hybrid model: YAML data (per-context permissions) + Rego logic (evaluation rules). Built-in decision logging. |
| **Readiness Gate** | A field-level condition in context.yaml. Specifies `requires_fields` (terms that must be extracted) and optional `requires_gates` (DAG dependencies on other gates). Observer evaluates gates after every extraction. When satisfied, triggers the configured action with the configured approval tier. |
| **Gate DAG** | Directed acyclic graph of readiness gate dependencies. E.g., ROE calculation depends on deal structuring completing first. Only used where there's a genuine ordering need — flat gates are the default. |
| **Approval Gateway** | Pattern within the Temporal Workflow: post card (Activity) → wait_condition (zero compute) → resume on Signal or timeout → escalate. |
| **Observer / Analyst / Calculator** | Three agent roles. Analyst extracts terms from documents (runs first on document events). Observer evaluates readiness gates against extracted terms and triggers actions (runs after every extraction). Calculator runs computations in a sandbox (triggered by gate actions). All execute as Activities on the shared worker pool. |
| **continue_as_new** | Temporal mechanism to reset workflow history when it grows too large (>10K events). Carries over agent state to a fresh workflow execution. Essential for deals that run for months. |
