from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ApprovalTier(str, Enum):
    AUTO_APPROVE = "auto_approve"
    SINGLE_APPROVAL = "single_approval"
    MAKER_CHECKER = "maker_checker"
    FOUR_EYES = "four_eyes"


class FactLifecycle(str, Enum):
    OBSERVED = "observed"
    EXTRACTED = "extracted"
    CANDIDATE = "candidate"
    CONFLICTED = "conflicted"
    APPROVED = "approved"
    COMMITTED = "committed"
    SUPERSEDED = "superseded"


class BundleStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class EventResolution:
    method: str
    confidence: float


@dataclass
class NormalizedEvent:
    event_id: str
    context_id: str
    event_type: str
    source: str
    timestamp: str
    payload: dict[str, Any]
    resolution: EventResolution
    artifact_hash: str | None = None
    artifact_version: int | None = None
    lineage_parent: str | None = None


@dataclass
class SourceMappings:
    sharepoint_paths: list[str] = field(default_factory=list)
    email_aliases: list[str] = field(default_factory=list)
    lockbox_accounts: list[str] = field(default_factory=list)
    clearpar_trade_ids: list[str] = field(default_factory=list)


@dataclass
class FactProvenance:
    source: str
    artifact_id: str
    artifact_version: int | None
    observed_at: str
    confidence: float


@dataclass
class FactRecord:
    fact_id: str
    context_id: str
    field: str
    value: Any
    lifecycle: FactLifecycle
    provenance: FactProvenance
    created_at: str
    status_reason: str = ""
    approved_by: str | None = None
    committed_at: str | None = None
    supersedes: str | None = None


@dataclass
class FieldConflict:
    field: str
    active_fact_ids: list[str] = field(default_factory=list)
    reason: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class ProposedChange:
    field: str
    from_fact_id: str | None
    to_fact_id: str
    reason: str


@dataclass
class DecisionBundle:
    bundle_id: str
    context_id: str
    title: str
    tier: ApprovalTier
    changes: list[ProposedChange]
    evidence_event_ids: list[str]
    status: BundleStatus = BundleStatus.PENDING
    created_at: str = field(default_factory=utc_now)
    approved_by: str | None = None
    notes: str | None = None


@dataclass
class ReadinessGate:
    gate_id: str
    requires_fields: list[str]
    requires_gates: list[str] = field(default_factory=list)
    min_confidence: float = 0.8
    max_age_hours: int | None = 24 * 90
    allowed_sources: list[str] | None = None
    approval_tier: ApprovalTier = ApprovalTier.SINGLE_APPROVAL
    action: str = "promote_fields"

    def max_age(self) -> timedelta | None:
        if self.max_age_hours is None:
            return None
        return timedelta(hours=self.max_age_hours)


@dataclass
class GateEvaluation:
    gate_id: str
    satisfied: bool
    missing_fields: list[str] = field(default_factory=list)
    conflicted_fields: list[str] = field(default_factory=list)
    stale_fields: list[str] = field(default_factory=list)
    low_confidence_fields: list[str] = field(default_factory=list)
    blocked_by_gates: list[str] = field(default_factory=list)


@dataclass
class ContextConfig:
    context_id: str
    name: str
    source_mappings: SourceMappings = field(default_factory=SourceMappings)
    source_priority: dict[str, int] = field(default_factory=dict)
    readiness_gates: dict[str, ReadinessGate] = field(default_factory=dict)
    tool_allowlist: list[str] = field(default_factory=list)
    tool_denylist: list[str] = field(default_factory=list)
    approval_tiers_by_action: dict[str, ApprovalTier] = field(default_factory=dict)

    def get_source_priority(self, source: str) -> int:
        # Lower is better. Unknown sources are lowest priority.
        return self.source_priority.get(source, 1_000)


@dataclass
class WorkingContextState:
    context_id: str
    pending_events: list[NormalizedEvent] = field(default_factory=list)
    candidate_fact_by_field: dict[str, str] = field(default_factory=dict)
    conflicts: dict[str, FieldConflict] = field(default_factory=dict)
    pending_bundles: dict[str, DecisionBundle] = field(default_factory=dict)
    gate_status: dict[str, bool] = field(default_factory=dict)
    seen_event_ids: set[str] = field(default_factory=set)
    seen_artifact_hashes: set[str] = field(default_factory=set)
    document_lineage: dict[str, str] = field(default_factory=dict)
    last_activity_at: str = field(default_factory=utc_now)


@dataclass
class CommittedBusinessState:
    context_id: str
    committed_fact_by_field: dict[str, str] = field(default_factory=dict)
    last_updated_at: str = field(default_factory=utc_now)

