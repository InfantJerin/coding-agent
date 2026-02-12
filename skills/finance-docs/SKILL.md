---
name: finance-docs
description: Loan-ops style financial document extraction and Q&A pack for section-indexed documents. Use when the agent must read credit agreements (or similar finance docs), extract key terms with evidence, and answer questions with reasons and citations.
---

# Finance Docs Skill

Use this loan-ops traversal policy for document tasks:

1. `load_documents`
2. `build_doc_map`
3. `extract_finance_signals` (schema + multi-pass extraction over index)
4. `search_in_doc`
5. `read_span`
6. `follow_reference`
7. `read_definition`
8. `write_scratchpad`
9. `quote_evidence`
10. `consistency_check`
11. `build_ops_answer`

## Extraction Method

For extraction requests, use this sequence:

1. Build structure index first (`sections`, `definitions`, `xrefs`, anchors).
2. Identify relevant section families for each target field.
3. Extract field values from those sections with definition context.
4. Run consistency checks and return unresolved items explicitly.

## Behavior Rules

- Always cite anchors in answers and extraction reasons.
- Prefer section/definition evidence over raw global scans.
- Follow references when a term depends on another section/definition.
- Record unresolved references/fields as open questions.
- Treat `document_type` as configurable:
  - Start with `credit_agreement`.
  - Reuse same workflow for other finance docs (for example, `compliance_certificate`, `rate_notice`) via schema changes.
- Load schema from YAML:
  - Built-in YAML by `document_type`.
  - Override with `metadata.schema_path` when user/developer provides a custom schema file.
- Use strategy-driven execution:
  - Parse and step sequence come from strategy YAML.
  - Override with `metadata.strategy_path` or `metadata.strategy_override`.
- For strict tool control during runs, set `metadata.tool_policy_override` with allow/deny lists.

## References

- Covenant and term checklist: `references/credit-agreement-fields.md`
- Compliance checklist: `references/compliance-certificate-fields.md`
- Rate notice checklist: `references/rate-notice-fields.md`
