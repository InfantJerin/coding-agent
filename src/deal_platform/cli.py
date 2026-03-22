from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from deal_platform.context_registry.registry import ContextRegistry
from deal_platform.context_registry.storage import LocalContextStore
from deal_platform.db.connection import DatabaseConnection
from deal_platform.db.schema import initialize_db
from deal_platform.workflows.deal_agent import TASK_QUEUE


async def _create_context(args: argparse.Namespace) -> int:
    config: dict[str, Any] = {"name": args.name}

    if args.config:
        import yaml

        with open(args.config) as f:
            config = yaml.safe_load(f)
        config.setdefault("name", args.name)

    if args.context_id:
        config["context_id"] = args.context_id

    # Connect to Temporal if available
    temporal_client = None
    try:
        from temporalio.client import Client

        temporal_client = await Client.connect(args.address)
    except Exception:
        print("Warning: Could not connect to Temporal. Creating context without starting workflow.")

    registry = ContextRegistry(temporal_client=temporal_client)
    context_id = await registry.create_context(config)
    print(f"Created context: {context_id}")
    return 0


async def _send_event(args: argparse.Namespace) -> int:
    from temporalio.client import Client

    client = await Client.connect(args.address)
    handle = client.get_workflow_handle(args.context_id)

    event = {
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
        "context_id": args.context_id,
        "event_type": args.type,
        "source": "cli",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": json.loads(args.payload),
        "resolution": {"method": "manual", "confidence": 1.0},
    }

    await handle.signal("on_event", event)
    print(f"Sent {args.type} event to {args.context_id}: {event['event_id']}")
    return 0


async def _get_status(args: argparse.Namespace) -> int:
    from temporalio.client import Client

    client = await Client.connect(args.address)
    handle = client.get_workflow_handle(args.context_id)
    status = await handle.query("get_status")
    print(json.dumps(status, indent=2))
    return 0


async def _list_contexts(args: argparse.Namespace) -> int:
    registry = ContextRegistry()
    contexts = await registry.list_contexts(status_filter=args.status)
    if not contexts:
        print("No contexts found.")
        return 0
    for ctx in contexts:
        print(f"  {ctx['context_id']}  {ctx.get('name', '')}  [{ctx.get('status', '?')}]  {ctx.get('created_at', '')}")
    return 0


async def _start_worker(args: argparse.Namespace) -> int:
    from deal_platform.workers.worker import run_worker

    await run_worker(temporal_address=args.address)
    return 0


async def _dispatch(args: argparse.Namespace) -> int:
    handlers = {
        "create-context": _create_context,
        "send-event": _send_event,
        "get-status": _get_status,
        "list-contexts": _list_contexts,
        "start-worker": _start_worker,
    }
    handler = handlers.get(args.command)
    if handler is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1
    return await handler(args)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deal Intelligence Agent Platform CLI"
    )
    parser.add_argument(
        "--address",
        default="localhost:7233",
        help="Temporal server address (default: localhost:7233)",
    )
    sub = parser.add_subparsers(dest="command")

    # create-context
    create_p = sub.add_parser("create-context", help="Create a new deal context")
    create_p.add_argument("--name", required=True, help="Deal name")
    create_p.add_argument("--config", help="Path to context.yaml template")
    create_p.add_argument("--context-id", help="Explicit context ID (auto-generated if omitted)")

    # send-event
    event_p = sub.add_parser("send-event", help="Send an event signal to a workflow")
    event_p.add_argument("--context-id", required=True, help="Target context ID")
    event_p.add_argument("--type", default="manual_trigger", help="Event type")
    event_p.add_argument("--payload", default="{}", help="JSON payload")

    # get-status
    status_p = sub.add_parser("get-status", help="Query workflow status")
    status_p.add_argument("--context-id", required=True, help="Target context ID")

    # list-contexts
    list_p = sub.add_parser("list-contexts", help="List all contexts")
    list_p.add_argument("--status", default=None, help="Filter by status")

    # start-worker
    sub.add_parser("start-worker", help="Start the Temporal worker")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    return asyncio.run(_dispatch(args))


if __name__ == "__main__":
    sys.exit(main())
