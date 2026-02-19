from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_core.models import TaskRequest
from agent_core.runner import GenericHeadlessAgent
from env_loader import load_env_file
from profiles.finance_docs import build_finance_docs_profile


def load_task(path: Path) -> TaskRequest:
    payload = json.loads(path.read_text())
    return TaskRequest(
        instruction=payload["instruction"],
        documents=[Path(p) for p in payload.get("documents", [])],
        questions=payload.get("questions", []),
        output_modes=payload.get("output_modes", ["report", "json"]),
        metadata=payload.get("metadata", {}),
    )


def run_chat_mode(deal_arg: str | None, initial_files: list[str] | None = None, debug: bool = False) -> int:
    from agent_core.chat_runner import ChatAgent
    from agent_core.session import DealStore, SessionStore
    from agent_core.tooling import ToolPolicy, ToolRegistry
    from llm.catalog import load_model_catalog
    from llm.providers import build_llm_client
    from llm.selection import resolve_model_ref
    from profiles.finance_docs import resolve_requested_model_from_env
    from tools.deal_tools import AddDocumentToDealTool, CreateDealTool, GetDealSummaryTool, ListDealsTool
    from tools.excel_tools import ExtractTablesTool, RunPythonTool
    from tools.retrieval_tools import BuildChunkIndexTool, ChunkDocMapSectionsTool, RetrieveChunksTool

    data_dir = Path("./data")
    deal_store = DealStore(data_dir=data_dir / "deals")
    session_store = SessionStore(data_dir=data_dir / "sessions")

    # Resolve deal
    deal_meta = None
    if deal_arg:
        if deal_arg.startswith("new:"):
            name = deal_arg[4:].strip() or "unnamed"
            deal_meta = deal_store.create(name)
            print(f"Created deal '{deal_meta.name}' (id: {deal_meta.deal_id})")
        else:
            deal_meta = deal_store.load(deal_arg)
            if deal_meta is None:
                print(f"Deal not found: {deal_arg}", file=sys.stderr)
                return 1
            print(f"Loaded deal '{deal_meta.name}' ({len(deal_meta.documents)} documents)")

    # Build LLM client
    import os
    catalog_path = (
        Path(os.getenv("AGENT_MODEL_CATALOG", "")).expanduser()
        if os.getenv("AGENT_MODEL_CATALOG")
        else None
    )
    catalog = load_model_catalog(catalog_path)
    model_ref = resolve_model_ref(catalog, resolve_requested_model_from_env())
    llm_client = build_llm_client(model_ref)

    if llm_client is None:
        print(
            "No LLM client available. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.",
            file=sys.stderr,
        )
        return 1

    workspace_dir = str(Path("./workspace") / deal_meta.deal_id) if deal_meta else "./workspace"
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)

    # Build profile + add deal tools
    profile = build_finance_docs_profile()
    deal_tools = {
        "create_deal": CreateDealTool(deal_store),
        "add_document_to_deal": AddDocumentToDealTool(deal_store),
        "get_deal_summary": GetDealSummaryTool(deal_store),
        "list_deals": ListDealsTool(deal_store),
    }
    combined_tools = {
        **profile.registry.tools,
        **deal_tools,
        "retrieve_chunks": RetrieveChunksTool(),
        "extract_tables": ExtractTablesTool(),
        "run_python": RunPythonTool(),
    }
    registry = ToolRegistry(tools=combined_tools)
    policy = ToolPolicy(allow=list(combined_tools.keys()), deny=[])

    # Load cached doc_map + chunk_index if deal has documents
    doc_map: dict = {}
    chunk_index: dict = {}
    if deal_meta:
        cached = deal_store.load_doc_map(deal_meta.deal_id)
        if cached:
            doc_map = cached
            print(f"Loaded cached document index ({len(doc_map.get('anchors', {}))} anchors)")
        cached_idx = deal_store.load_chunk_index(deal_meta.deal_id)
        if cached_idx:
            chunk_index = cached_idx

    session = session_store.create(deal_id=deal_meta.deal_id if deal_meta else None)
    agent = ChatAgent(
        session=session,
        deal_meta=deal_meta,
        doc_map=doc_map,
        chunk_index=chunk_index,
        registry=registry,
        policy=policy,
        llm_client=llm_client,
        session_store=session_store,
        debug=debug,
        workspace_dir=workspace_dir,
    )

    def _index_document(doc_path: str) -> None:
        nonlocal doc_map, deal_meta, chunk_index
        from pathlib import Path as P
        from tools.document_tools import BuildDocMapTool, LoadDocumentsTool

        p = P(doc_path)
        if not p.exists():
            print(f"File not found: {doc_path}")
            return

        print(f"Indexing {doc_path} ...")
        load_tool = LoadDocumentsTool()
        doc_store = load_tool.run(documents=[str(p)])

        build_tool = BuildDocMapTool(llm_client=llm_client)
        new_map = build_tool.run(document_store=doc_store, parse_strategy="legal_contract")

        # Merge into existing doc_map (simple extend for sections/anchors/definitions/xrefs)
        if doc_map:
            for key in ("sections", "definitions", "xrefs"):
                doc_map.setdefault(key, []).extend(new_map.get(key, []))
            doc_map.setdefault("anchors", {}).update(new_map.get("anchors", {}))
            # Merge document_store documents list
            existing_docs = doc_map.setdefault("document_store", {}).setdefault("documents", [])
            existing_docs.extend(new_map.get("document_store", {}).get("documents", []))
        else:
            doc_map = new_map

        agent.update_doc_map(doc_map)

        chunks = ChunkDocMapSectionsTool().run(doc_map)
        chunk_index = BuildChunkIndexTool().run(chunks)
        agent.update_chunk_index(chunk_index)
        print(f"BM25 index: {len(chunks)} chunks")

        if deal_meta:
            deal_store.add_document(
                deal_id=deal_meta.deal_id,
                path=str(p),
                doc_type="auto",
                role="primary",
            )
            deal_store.save_doc_map(deal_meta.deal_id, doc_map)
            deal_store.save_chunk_index(deal_meta.deal_id, chunk_index)
            deal_meta = deal_store.load(deal_meta.deal_id)
            agent.deal_meta = deal_meta

        anchors = len(doc_map.get("anchors", {}))
        sections = len(doc_map.get("sections", []))
        print(f"Indexed: {anchors} anchors, {sections} sections")

    for f in (initial_files or []):
        _index_document(f)

    print("Chat mode. Type /quit to exit, /load <path> to index a document, /deals to list deals.")
    print(f"Session: {session.session_id}")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
            break

        if user_input.startswith("/load "):
            path_str = user_input[6:].strip()
            _index_document(path_str)
            continue

        if user_input == "/deals":
            deals = deal_store.list_deals()
            if not deals:
                print("No deals saved.")
            for d in deals:
                print(f"  {d.deal_id}  {d.name}  ({len(d.documents)} docs)")
            continue

        if user_input == "/session":
            print(f"Session: {session.session_id}, messages: {len(session.messages)}")
            continue

        try:
            reply = agent.send(user_input)
            print(reply)
        except Exception as exc:
            print(f"[error] {exc}", file=sys.stderr)

    return 0


def main() -> int:
    load_env_file(Path(".env"))

    parser = argparse.ArgumentParser(description="Run generic agent (default) or headless batch mode")
    parser.add_argument(
        "--mode",
        choices=["agent", "headless", "chat"],
        default="agent",
        help="Execution mode. Defaults to agent.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Shortcut to run in headless mode (equivalent to --mode headless).",
    )
    parser.add_argument("--task", help="Path to task JSON (required for headless mode)")
    parser.add_argument("--output-dir", help="Directory for artifacts (required for headless mode)")
    parser.add_argument("--query", help="User query for agent mode")
    parser.add_argument(
        "--documents",
        nargs="*",
        default=[],
        help="Document paths for agent mode",
    )
    parser.add_argument(
        "--instruction",
        default="Answer the user query using provided documents.",
        help="Instruction context for agent mode",
    )
    parser.add_argument(
        "--show-trace",
        action="store_true",
        help="Print tool trace in agent mode",
    )
    parser.add_argument("--document-type", help="Document type hint for schema/strategy selection in agent mode")
    parser.add_argument("--schema-path", help="Optional YAML schema path override for extraction")
    parser.add_argument("--strategy-path", help="Optional YAML strategy path override for runner sequencing")
    parser.add_argument(
        "--deal",
        help="Chat mode deal: existing deal_id, or 'new:<name>' to create one",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Documents to load immediately (chat mode only)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print ReAct loop internals (tool calls, results, turn counts) to stderr",
    )
    args = parser.parse_args()

    mode = "headless" if args.headless else args.mode

    if mode == "chat":
        return run_chat_mode(deal_arg=args.deal, initial_files=args.files, debug=args.debug)

    profile = build_finance_docs_profile()
    runner = GenericHeadlessAgent(profile.registry, profile.policy)

    if mode == "headless":
        if not args.task or not args.output_dir:
            raise SystemExit("Headless mode requires --task and --output-dir")
        task = load_task(Path(args.task))
        result = runner.run(task, Path(args.output_dir))
        print(result.message)
        for artifact in result.artifacts:
            print(f"- {artifact.name}: {artifact.path}")
        return 0

    if not args.query:
        raise SystemExit("Agent mode requires --query")
    if not args.documents:
        raise SystemExit("Agent mode requires at least one path in --documents")

    response, trace = runner.respond(
        instruction=args.instruction,
        documents=[Path(p) for p in args.documents],
        query=args.query,
        metadata={
            "document_type": args.document_type,
            "schema_path": args.schema_path,
            "strategy_path": args.strategy_path,
        },
    )
    print(response)
    if args.show_trace:
        print("\n## Trace")
        print(json.dumps(trace, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
