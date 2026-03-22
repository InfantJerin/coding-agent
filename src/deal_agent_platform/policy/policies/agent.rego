package deal_agent.policy

default allow := false
default approval_required := "auto_approve"

allow if {
  is_tool_allowed
  is_context_aligned
  is_data_scoped
}

is_tool_allowed if {
  some tool
  tool := input.tool_name
  tool in data.contexts[input.agent_context_id].tool_policy.allow
  not tool in data.contexts[input.agent_context_id].tool_policy.deny
}

is_context_aligned if {
  input.tool_args.context_id == input.agent_context_id
}

is_data_scoped if {
  startswith(input.tool_args.s3_path, sprintf("s3://agent-memory/%s/", [input.agent_context_id]))
}

approval_required := tier if {
  tier := data.contexts[input.agent_context_id].approval_policy[input.tool_name]
}
