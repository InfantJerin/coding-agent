from __future__ import annotations

import argparse
import json
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


def main() -> int:
    load_env_file(Path(".env"))

    parser = argparse.ArgumentParser(description="Run generic agent (default) or headless batch mode")
    parser.add_argument(
        "--mode",
        choices=["agent", "headless"],
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
    args = parser.parse_args()

    mode = "headless" if args.headless else args.mode
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
    )
    print(response)
    if args.show_trace:
        print("\n## Trace")
        print(json.dumps(trace, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
