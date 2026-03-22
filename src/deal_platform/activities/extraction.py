from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from temporalio import activity

from tools.document_tools import BuildDocMapTool, LoadDocumentsTool
from tools.finance_tools import ExtractFinanceSignalsTool


@activity.defn
async def extract_terms(
    context_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Extract terms from a document using the existing extraction pipeline.

    Args:
        context_id: The deal context ID.
        payload: Event payload with at least 'document_ref' (file path)
                 and optionally 'doc_type'.

    Returns:
        Dict of {field_name: {value, source, extracted_at}} in ExtractedTerm format.
    """
    document_ref = payload.get("document_ref", "")
    doc_type = payload.get("doc_type")

    if not document_ref:
        return {}

    doc_path = Path(document_ref)
    if not doc_path.exists():
        activity.logger.warning(f"Document not found: {document_ref}")
        return {}

    # Step 1: Load document
    loader = LoadDocumentsTool()
    loaded = loader.run(documents=[str(doc_path)])

    # Step 2: Build document map
    builder = BuildDocMapTool(llm_client=None)  # No LLM for doc map in Phase 1
    doc_map: dict[str, Any] | None = None
    full_text = ""
    if loaded.get("documents"):
        doc = loaded["documents"][0]
        doc_map = builder.run(documents=loaded)
        full_text = "\n".join(
            page.get("text", "") for page in doc.get("pages", [])
        )

    # Step 3: Extract signals using existing pipeline
    extractor = ExtractFinanceSignalsTool(llm_client=None)
    extraction = extractor.run(
        text=full_text,
        instruction=f"Extract terms for context {context_id}",
        doc_map=doc_map,
        document_type=doc_type,
    )

    # Step 4: Convert field_extraction to ExtractedTerm format
    now = datetime.now(timezone.utc).isoformat()
    source_name = doc_path.name
    terms: dict[str, dict[str, Any]] = {}

    # From schema-driven field extraction
    for field_name, field_data in extraction.get("field_extraction", {}).items():
        if isinstance(field_data, dict) and field_data.get("found"):
            terms[field_name] = {
                "value": field_data.get("value"),
                "source": source_name,
                "extracted_at": now,
            }

    # From regex signal extraction
    for signal_name, values in extraction.get("signals", {}).items():
        if values:
            terms[signal_name] = {
                "value": values[0] if len(values) == 1 else values,
                "source": source_name,
                "extracted_at": now,
            }

    return terms
