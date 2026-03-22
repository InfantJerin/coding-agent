from __future__ import annotations

from deal_agent_platform.application.interfaces import (
    ActivityPolicyDecision,
    ActivityPolicyInput,
    ContextConfigStore,
)
from deal_agent_platform.domain import ApprovalTier


class OpaLikePolicyEngine:
    """
    Scaffold implementation of the 4-check pipeline:
    tool allowlist -> context boundary -> data scope -> approval tier.
    """

    def __init__(self, config_store: ContextConfigStore) -> None:
        self._config_store = config_store

    def evaluate(self, input_data: ActivityPolicyInput) -> ActivityPolicyDecision:
        config = self._config_store.get(input_data.agent_context_id)
        if config is None:
            return ActivityPolicyDecision(
                allow=False,
                reason=f"unknown_context:{input_data.agent_context_id}",
            )

        # 1) Tool allow/deny
        tool_name = input_data.tool_name
        if tool_name in set(config.tool_denylist):
            return ActivityPolicyDecision(allow=False, reason="tool_denied")
        if config.tool_allowlist and tool_name not in set(config.tool_allowlist):
            return ActivityPolicyDecision(allow=False, reason="tool_not_allowlisted")

        # 2) Context boundary
        arg_context = input_data.tool_args.get("context_id")
        if arg_context is not None and str(arg_context) != input_data.agent_context_id:
            return ActivityPolicyDecision(allow=False, reason="context_boundary_violation")

        # 3) Data scope
        s3_path = input_data.tool_args.get("s3_path")
        if s3_path is not None:
            expected = f"s3://agent-memory/{input_data.agent_context_id}/"
            if not str(s3_path).startswith(expected):
                return ActivityPolicyDecision(allow=False, reason="s3_scope_violation")
        query_context = input_data.tool_args.get("query_context_id")
        if query_context is not None and str(query_context) != input_data.agent_context_id:
            return ActivityPolicyDecision(allow=False, reason="query_scope_violation")

        # 4) Approval tier
        tier = config.approval_tiers_by_action.get(tool_name, ApprovalTier.AUTO_APPROVE)
        return ActivityPolicyDecision(
            allow=True,
            reason="allow",
            approval_required=tier,
            approvers=[],
        )
