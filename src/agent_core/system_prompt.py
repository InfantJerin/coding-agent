from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.session import DealMeta

_DEFAULT_IDENTITY = (
    "You are a financial document analyst. You help users understand complex "
    "financial agreements, extract key terms, and navigate deal structures.\n\n"
    "When working with documents:\n"
    "- Always cite your sources with section/anchor references\n"
    "- When a term is ambiguous, surface it as an open question\n"
    "- For amendments, note which document is the authoritative source\n"
    "- Be concise but precise"
)

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_in_doc": "Search sections/definitions/blocks in the document index",
    "retrieve_chunks": "BM25 full-text search over section body text — best for topic/concept queries",
    "read_span": "Read a text span by anchor or page range",
    "read_definition": "Look up a defined term",
    "follow_reference": "Resolve a cross-reference to its target text",
    "quote_evidence": "Extract a quoted evidence block",
    "extract_finance_signals": "Run schema-based field extraction on the loaded documents",
    "create_deal": "Create a new deal package",
    "add_document_to_deal": "Add a document to the current deal",
    "get_deal_summary": "Show the current deal's document list and status",
    "list_deals": "List all saved deals",
    "write_scratchpad": "Store an intermediate finding for later reference",
    "read_scratchpad": "Retrieve a stored finding",
    "extract_tables": "Extract structured table rows/columns from a document page range",
    "run_python": "Execute Python code for calculations; generate Excel files with citations in workspace",
}


def build_chat_system_prompt(
    deal_meta: DealMeta | None,
    available_tool_names: list[str],
    extracted_terms_count: int = 0,
) -> str:
    identity_path = Path("workspace/IDENTITY.md")
    if identity_path.exists():
        identity = identity_path.read_text().strip()
        # Strip the markdown heading if present
        lines = identity.splitlines()
        if lines and lines[0].startswith("#"):
            lines = lines[1:]
        identity = "\n".join(lines).strip()
    else:
        identity = _DEFAULT_IDENTITY

    parts: list[str] = [identity, ""]

    if deal_meta:
        parts.append(f"## Current Deal: {deal_meta.name}")
        parts.append(f"Deal ID: {deal_meta.deal_id}")
        if deal_meta.documents:
            parts.append("Documents:")
            for doc in deal_meta.documents:
                parts.append(f"  - [{doc.role}] {doc.path} (type: {doc.doc_type})")
        else:
            parts.append("No documents loaded yet. Use /load <path> to add one.")
        if extracted_terms_count > 0:
            parts.append(f"Extracted fields: {extracted_terms_count} terms indexed.")
        parts.append("")
    else:
        parts.append("No deal loaded. Use 'create_deal' or /load to get started.")
        parts.append("")

    if available_tool_names:
        parts.append("## Available Tools")
        for name in available_tool_names:
            desc = _TOOL_DESCRIPTIONS.get(name, "")
            parts.append(f"- **{name}**: {desc}" if desc else f"- **{name}**")
        parts.append("")

    parts.append(
        "When you need to look something up, use your tools. "
        "Always ground your answers in document evidence. "
        "If you cannot find evidence, say so clearly.\n\n"
        "**Planning:** Before making any tool calls, briefly state your plan — which tools you "
        "will call and why. Then execute all initial searches in a single batch. Only make a "
        "follow-up round of tool calls if the first batch returned insufficient results.\n\n"
        "**Search discipline:** If a search returns the same results as a previous search, "
        "do not repeat it with only minor wording changes. "
        "After 2–3 searches that yield no new evidence, stop searching and synthesize an answer "
        "from what you have found — stating clearly what you could and could not locate."
    )

    return "\n".join(parts)
