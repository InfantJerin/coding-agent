from __future__ import annotations

import re
from typing import Any

from deal_platform.models import PolicyDecision
from deal_platform.policy.decision_log import DecisionLogger


def _compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a glob-style pattern (with * wildcard) to regex."""
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.compile(rf"^{escaped}$")


def _matches(name: str, patterns: list[str]) -> bool:
    return any(_compile_pattern(p).match(name) for p in patterns)


class PolicyEngine:
    """In-process 4-check policy pipeline (OPA-structured, swappable later).

    Checks in order:
        1. Tool Allowlist — is the tool permitted for this context?
        2. Context Boundary — does tool_args.context_id match the agent's context?
        3. Data Scope — are file paths / DB filters scoped to the agent's context?
        4. Approval Tier — what approval level does this action need?
    """

    def __init__(self, decision_logger: DecisionLogger | None = None):
        self.decision_logger = decision_logger

    def evaluate(
        self,
        *,
        tool_name: str,
        agent_context_id: str,
        tool_args: dict[str, Any],
        context_config: dict[str, Any],
    ) -> PolicyDecision:
        denied_checks: list[str] = []

        # Check 1: Tool Allowlist
        tool_policy = context_config.get("tool_policy", {"allow": ["*"], "deny": []})
        allowed, reason = self._check_tool_allowed(tool_name, tool_policy)
        if not allowed:
            denied_checks.append("tool_allowed")
            decision = PolicyDecision(
                allow=False,
                reason=reason,
                denied_checks=denied_checks,
            )
            self._log(agent_context_id, tool_name, tool_args, decision)
            return decision

        # Check 2: Context Boundary
        allowed, reason = self._check_context_boundary(agent_context_id, tool_args)
        if not allowed:
            denied_checks.append("context_boundary")
            decision = PolicyDecision(
                allow=False,
                reason=reason,
                denied_checks=denied_checks,
            )
            self._log(agent_context_id, tool_name, tool_args, decision)
            return decision

        # Check 3: Data Scope
        allowed, reason = self._check_data_scope(agent_context_id, tool_args)
        if not allowed:
            denied_checks.append("data_scope")
            decision = PolicyDecision(
                allow=False,
                reason=reason,
                denied_checks=denied_checks,
            )
            self._log(agent_context_id, tool_name, tool_args, decision)
            return decision

        # Check 4: Approval Tier
        approval_policy = context_config.get("approval_policy", {})
        tier = self._check_approval_tier(tool_name, approval_policy)
        approvers = self._get_approvers(tier, approval_policy)

        decision = PolicyDecision(
            allow=True,
            approval_required=tier,
            approvers=approvers,
            reason="all checks passed",
        )
        self._log(agent_context_id, tool_name, tool_args, decision)
        return decision

    def _check_tool_allowed(
        self, tool_name: str, tool_policy: dict[str, Any]
    ) -> tuple[bool, str]:
        deny = tool_policy.get("deny", [])
        allow = tool_policy.get("allow", ["*"])

        if _matches(tool_name, deny):
            return False, f"tool '{tool_name}' is in deny list"
        if not _matches(tool_name, allow):
            return False, f"tool '{tool_name}' is not in allow list"
        return True, ""

    def _check_context_boundary(
        self, agent_context_id: str, tool_args: dict[str, Any]
    ) -> tuple[bool, str]:
        target_ctx = tool_args.get("context_id")
        if target_ctx is not None and target_ctx != agent_context_id:
            return False, f"cross-context access denied: agent={agent_context_id}, target={target_ctx}"
        return True, ""

    def _check_data_scope(
        self, agent_context_id: str, tool_args: dict[str, Any]
    ) -> tuple[bool, str]:
        path = tool_args.get("path", "")
        if path and agent_context_id not in path:
            return False, f"path '{path}' is outside context scope"
        return True, ""

    def _check_approval_tier(
        self, tool_name: str, approval_policy: dict[str, Any]
    ) -> str | None:
        # Check each tier from most restrictive to least
        for tier in ("four_eyes", "maker_checker", "single_approval"):
            tier_config = approval_policy.get(tier, {})
            actions = tier_config.get("actions", [])
            if tool_name in actions:
                return tier

        auto = approval_policy.get("auto_approve", [])
        if tool_name in auto or not approval_policy:
            return None  # auto-approved

        # Default: deny-by-default means require single_approval for unknown actions
        return "single_approval"

    def _get_approvers(
        self, tier: str | None, approval_policy: dict[str, Any]
    ) -> list[str]:
        if tier is None:
            return []
        tier_config = approval_policy.get(tier, {})
        return tier_config.get("approvers", [])

    def _log(
        self,
        context_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        decision: PolicyDecision,
    ) -> None:
        if self.decision_logger is None:
            return
        from dataclasses import asdict

        self.decision_logger.log(
            context_id,
            {
                "tool_name": tool_name,
                "context_id": context_id,
                "decision": asdict(decision),
            },
        )
