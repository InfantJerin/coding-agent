from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Normalized Event (Temporal Signal payload) ──


@dataclass
class NormalizedEvent:
    """Event sent as a Temporal Signal to a deal workflow."""

    event_id: str  # "evt-<uuid>"
    context_id: str  # "deal-abc-2026"
    event_type: str  # "document_received" | "manual_trigger" | "app_event" | "approval_response"
    source: str  # "api" | "sharepoint" | "email" | "lockbox" | "clearpar" | "bql" | "teams"
    timestamp: str  # ISO 8601
    payload: dict[str, Any] = field(default_factory=dict)
    resolution: dict[str, Any] = field(
        default_factory=lambda: {"method": "manual", "confidence": 1.0}
    )


# ── Extracted Term (single field from a document) ──


@dataclass
class ExtractedTerm:
    """One extracted field value with provenance."""

    value: Any
    source: str  # document filename
    extracted_at: str  # ISO 8601
    previous: dict[str, Any] | None = None  # only set if value was overwritten


# ── Gate Status ──


@dataclass
class GateStatus:
    """Readiness gate evaluation state."""

    gate_name: str
    satisfied: bool = False
    satisfied_at: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    missing_gates: list[str] = field(default_factory=list)


# ── Agent Memory Bundle (loaded/saved as unit via Activities) ──


@dataclass
class AgentMemory:
    """Everything stored at data/agent_memory/{context_id}/."""

    context_id: str
    memory_md: str = ""
    extracted_terms: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)


# ── Context Config (parsed from context.yaml) ──


@dataclass
class ContextConfig:
    """Deal context configuration — what the agent knows about its deal."""

    context_id: str
    name: str
    status: str = "active"  # "active" | "paused" | "closed"
    created_at: str = ""
    created_by: str = ""
    temporal: dict[str, Any] = field(
        default_factory=lambda: {
            "task_queue": "deal-agent-tasks",
            "workflow_type": "DealAgentWorkflow",
        }
    )
    sources: dict[str, Any] = field(default_factory=dict)
    readiness_gates: dict[str, Any] = field(default_factory=dict)
    approval_policy: dict[str, Any] = field(default_factory=dict)
    tool_policy: dict[str, Any] = field(
        default_factory=lambda: {"allow": ["*"], "deny": []}
    )
    outbound: dict[str, Any] = field(default_factory=dict)
    agent: dict[str, Any] = field(
        default_factory=lambda: {
            "model": "anthropic/claude-sonnet-4-6",
            "max_turns_per_wake": 20,
            "strategy": "finance_deal",
            "profile": "finance-docs",
        }
    )


# ── Policy Decision ──


@dataclass
class PolicyDecision:
    """Result of the 4-check policy evaluation pipeline."""

    allow: bool
    approval_required: str | None = None  # None | "auto_approve" | "single_approval" | "maker_checker" | "four_eyes"
    approvers: list[str] = field(default_factory=list)
    reason: str = ""
    denied_checks: list[str] = field(default_factory=list)


# ── Workflow State (carried across continue_as_new) ──


@dataclass
class WorkflowState:
    """Serializable snapshot of workflow state."""

    context_id: str
    extracted_terms: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_events: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    history_length: int = 0
    last_activity: str = ""  # ISO 8601
