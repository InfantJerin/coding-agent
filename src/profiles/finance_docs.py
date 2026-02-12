from __future__ import annotations

import os
from pathlib import Path

from agent_core.tooling import ToolPolicy, ToolRegistry
from llm.catalog import load_model_catalog
from llm.providers import build_llm_client
from llm.selection import resolve_model_ref
from profiles.base import AgentProfile
from tools.bash_tools import SafeBashTool
from tools.document_tools import (
    BuildDocMapTool,
    ConsistencyCheckTool,
    FollowReferenceTool,
    GotoPageTool,
    LoadDocumentsTool,
    OpenAtAnchorTool,
    OpenDocTool,
    QuoteEvidenceTool,
    ReadDefinitionTool,
    ReadSpanTool,
    SearchInDocTool,
)
from tools.finance_tools import BuildOpsAnswerTool, BuildSummaryReportTool, ExtractFinanceSignalsTool
from tools.retrieval_tools import BuildChunkIndexTool, ChunkDocMapSectionsTool, ChunkDocumentTool, RetrieveChunksTool
from tools.state_tools import AppendReadingTrailTool, ReadScratchpadTool, WriteScratchpadTool


def resolve_requested_model_from_env() -> str | None:
    explicit_model = os.getenv("AGENT_MODEL", "").strip()
    if explicit_model:
        return explicit_model
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai/gpt-4.1-mini"
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return "anthropic/claude-3-5-sonnet-latest"
    return None


def build_finance_docs_profile() -> AgentProfile:
    catalog_path = Path(os.getenv("AGENT_MODEL_CATALOG", "")).expanduser() if os.getenv("AGENT_MODEL_CATALOG") else None
    catalog = load_model_catalog(catalog_path)
    requested = resolve_requested_model_from_env()
    model_ref = resolve_model_ref(catalog, requested)
    llm_client = build_llm_client(model_ref)
    model_label = f"{model_ref.provider}/{model_ref.model}" if model_ref else None

    tools = {
        "load_documents": LoadDocumentsTool(),
        "build_doc_map": BuildDocMapTool(llm_client=llm_client),
        "open_doc": OpenDocTool(),
        "goto_page": GotoPageTool(),
        "open_at_anchor": OpenAtAnchorTool(),
        "read_span": ReadSpanTool(),
        "search_in_doc": SearchInDocTool(),
        "follow_reference": FollowReferenceTool(),
        "read_definition": ReadDefinitionTool(),
        "quote_evidence": QuoteEvidenceTool(),
        "consistency_check": ConsistencyCheckTool(),
        "write_scratchpad": WriteScratchpadTool(),
        "read_scratchpad": ReadScratchpadTool(),
        "append_reading_trail": AppendReadingTrailTool(),
        "safe_bash": SafeBashTool(),
        "extract_finance_signals": ExtractFinanceSignalsTool(),
        "build_ops_answer": BuildOpsAnswerTool(llm_client=llm_client, model_label=model_label),
        "build_summary_report": BuildSummaryReportTool(),
        "chunk_document": ChunkDocumentTool(),
        "chunk_doc_map_sections": ChunkDocMapSectionsTool(),
        "build_chunk_index": BuildChunkIndexTool(),
        "retrieve_chunks": RetrieveChunksTool(),
    }

    policy = ToolPolicy(
        allow=[
            "load_documents",
            "build_doc_map",
            "open_doc",
            "goto_page",
            "open_at_anchor",
            "read_span",
            "search_in_doc",
            "follow_reference",
            "read_definition",
            "quote_evidence",
            "consistency_check",
            "write_scratchpad",
            "read_scratchpad",
            "append_reading_trail",
            "extract_finance_signals",
            "build_ops_answer",
            "build_summary_report",
            "chunk_document",
            "chunk_doc_map_sections",
            "build_chunk_index",
            "retrieve_chunks",
            "safe_bash",
        ],
        deny=[],
    )
    return AgentProfile(name="finance-docs", registry=ToolRegistry(tools=tools), policy=policy)
