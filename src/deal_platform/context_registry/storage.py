from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


class LocalContextStore:
    """Filesystem-backed context store (stands in for S3 in Phase 1).

    Directory layout per context mirrors the architecture's S3 layout:
        data/agent_memory/{context_id}/
            context.yaml
            MEMORY.md
            extracted_terms.json
            gate_status.json
            events.jsonl
            state.json
            audit/
                decisions.jsonl
    """

    def __init__(self, base_dir: Path = Path("./data/agent_memory")):
        self.base_dir = base_dir

    def create(self, context_id: str, config: dict[str, Any]) -> None:
        """Create context directory structure and write initial files."""
        ctx_dir = self.base_dir / context_id
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "audit").mkdir(exist_ok=True)

        # Write context.yaml
        with open(ctx_dir / "context.yaml", "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        # Initialize empty files
        (ctx_dir / "MEMORY.md").write_text("")
        (ctx_dir / "extracted_terms.json").write_text("{}")
        (ctx_dir / "gate_status.json").write_text("{}")
        (ctx_dir / "events.jsonl").write_text("")
        (ctx_dir / "state.json").write_text("{}")
        (ctx_dir / "audit" / "decisions.jsonl").write_text("")

    def load_config(self, context_id: str) -> dict[str, Any] | None:
        """Read and parse context.yaml. Returns None if not found."""
        config_path = self.base_dir / context_id / "context.yaml"
        if not config_path.exists():
            return None
        with open(config_path) as f:
            return yaml.safe_load(f)

    def save_config(self, context_id: str, config: dict[str, Any]) -> None:
        """Write context.yaml."""
        config_path = self.base_dir / context_id / "context.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    def list_contexts(self) -> list[str]:
        """List all context_id directories that have a context.yaml."""
        if not self.base_dir.exists():
            return []
        return [
            d.name
            for d in sorted(self.base_dir.iterdir())
            if d.is_dir() and (d / "context.yaml").exists()
        ]

    def exists(self, context_id: str) -> bool:
        return (self.base_dir / context_id / "context.yaml").exists()

    def load_memory_file(self, context_id: str, filename: str) -> str:
        """Read a raw file from the context directory."""
        path = self.base_dir / context_id / filename
        if not path.exists():
            return "" if filename.endswith((".md", ".jsonl")) else "{}"
        return path.read_text()

    def save_memory_file(self, context_id: str, filename: str, content: str) -> None:
        """Write a raw file to the context directory."""
        path = self.base_dir / context_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def append_memory_file(self, context_id: str, filename: str, line: str) -> None:
        """Append a line to a JSONL file in the context directory."""
        path = self.base_dir / context_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(line.rstrip("\n") + "\n")
