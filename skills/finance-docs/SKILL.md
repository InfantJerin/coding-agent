---
name: finance-docs
description: Financial document extraction and Q&A pack for PDFs and text agreements. Use when the agent must ingest financial/legal documents, extract covenant and pricing terms, build retrievable chunks, and answer questions with evidence citations.
---

# Finance Docs Skill

Use this ops-style traversal policy for document tasks:

1. `load_documents`
2. `build_doc_map`
3. `search_in_doc`
4. `read_span`
5. `follow_reference`
6. `read_definition`
7. `write_scratchpad`
8. `quote_evidence`
9. `consistency_check`
10. `build_ops_answer`

Always cite anchors in answers and maintain a reading trail.
When references are unresolved, record them in open questions and report clearly.

## References

- Covenant and term checklist: `references/credit-agreement-fields.md`
