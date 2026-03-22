from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class DecisionLogger:
    """Append-only JSONL logger for policy decisions."""

    def __init__(self, base_dir: Path = Path("./data/agent_memory")):
        self.base_dir = base_dir

    def log(self, context_id: str, decision: dict) -> None:
        audit_dir = self.base_dir / context_id / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **decision,
        }
        with open(audit_dir / "decisions.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
