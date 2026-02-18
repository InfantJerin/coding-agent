from __future__ import annotations

# Tools exposed in chat mode
CHAT_TOOLS: list[str] = [
    "search_in_doc",
    "retrieve_chunks",
    "read_span",
    "read_definition",
    "follow_reference",
    "quote_evidence",
    "extract_finance_signals",
    "create_deal",
    "add_document_to_deal",
    "get_deal_summary",
    "list_deals",
    "write_scratchpad",
    "read_scratchpad",
]

# Anthropic tool JSON schemas (only user-facing parameters — no doc_map, no state)
TOOL_SPECS: dict[str, dict] = {
    "search_in_doc": {
        "name": "search_in_doc",
        "description": "Search for sections, definitions, or blocks in the loaded document index.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "scope": {
                    "type": "string",
                    "enum": ["doc", "section", "definition"],
                    "description": (
                        "Search scope: "
                        "'doc' searches all body text (best for content/keyword queries); "
                        "'section' searches section titles/numbers only (use to navigate to a known section); "
                        "'definition' searches defined terms only."
                    ),
                },
                "top_k": {"type": "integer", "description": "Max results to return (default 8)"},
            },
            "required": ["query"],
        },
    },
    "retrieve_chunks": {
        "name": "retrieve_chunks",
        "description": "BM25 full-text search over section content. Use this to find sections that discuss a topic by actual text, not just title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic or phrase to search for"},
                "top_k": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
    },
    "read_span": {
        "name": "read_span",
        "description": "Read a text span by anchor or page range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "anchor": {"type": "string", "description": "Anchor ID to start reading from"},
                "page_range": {
                    "type": "object",
                    "description": "Page range to read, e.g. {start: 1, end: 3}",
                    "properties": {
                        "start": {"type": "integer"},
                        "end": {"type": "integer"},
                    },
                },
                "doc_id": {"type": "string", "description": "Document ID (optional)"},
            },
        },
    },
    "read_definition": {
        "name": "read_definition",
        "description": "Look up the definition of a term in the document.",
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "The term to look up"},
                "doc_id": {"type": "string", "description": "Document ID (optional)"},
            },
            "required": ["term"],
        },
    },
    "follow_reference": {
        "name": "follow_reference",
        "description": "Resolve a cross-reference by ref_id or target text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref_id": {"type": "string", "description": "Reference ID"},
                "target_text": {"type": "string", "description": "Reference text to resolve"},
                "doc_id": {"type": "string", "description": "Document ID (optional)"},
            },
        },
    },
    "quote_evidence": {
        "name": "quote_evidence",
        "description": "Retrieve quoted evidence blocks for given anchor IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "anchors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of anchor IDs to quote",
                },
            },
            "required": ["anchors"],
        },
    },
    "extract_finance_signals": {
        "name": "extract_finance_signals",
        "description": "Run schema-based financial field extraction on the loaded documents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Document type hint (e.g. credit_agreement, compliance_certificate)",
                },
                "instruction": {"type": "string", "description": "Extraction instruction"},
            },
        },
    },
    "create_deal": {
        "name": "create_deal",
        "description": "Create a new deal package.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Deal name"},
            },
            "required": ["name"],
        },
    },
    "add_document_to_deal": {
        "name": "add_document_to_deal",
        "description": "Add a document to the current deal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "string", "description": "Deal ID"},
                "path": {"type": "string", "description": "Path to the document file"},
                "doc_type": {"type": "string", "description": "Document type (default: auto)"},
                "role": {
                    "type": "string",
                    "enum": ["primary", "amendment", "supplement"],
                    "description": "Document role (default: primary)",
                },
            },
            "required": ["deal_id", "path"],
        },
    },
    "get_deal_summary": {
        "name": "get_deal_summary",
        "description": "Get the current deal's document list and index status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "string", "description": "Deal ID"},
            },
            "required": ["deal_id"],
        },
    },
    "list_deals": {
        "name": "list_deals",
        "description": "List all saved deals.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "write_scratchpad": {
        "name": "write_scratchpad",
        "description": "Store an intermediate finding under a named key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Storage key"},
                "content": {"type": "string", "description": "Value to store"},
            },
            "required": ["key", "content"],
        },
    },
    "read_scratchpad": {
        "name": "read_scratchpad",
        "description": "Retrieve a previously stored finding by key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Storage key to retrieve"},
            },
            "required": ["key"],
        },
    },
}

# Parameters that are pre-bound by the context (not passed by the LLM)
TOOL_BOUND_PARAMS: dict[str, list[str]] = {
    "search_in_doc": ["doc_map"],
    "retrieve_chunks": ["chunk_index"],
    "read_span": ["doc_map"],
    "read_definition": ["doc_map"],
    "follow_reference": ["doc_map"],
    "quote_evidence": ["doc_map"],
    "extract_finance_signals": ["doc_map", "text"],
    "write_scratchpad": ["state"],
    "read_scratchpad": ["state"],
}
