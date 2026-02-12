from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MemoryStore:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, *, kind: str, content: dict[str, Any]) -> None:
        self.entries.append({"kind": kind, "content": content})

    def query(self, text: str, top_k: int = 5) -> list[dict[str, Any]]:
        tokens = {tok.lower() for tok in text.split() if tok.strip()}
        if not tokens:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in self.entries:
            blob = json.dumps(row, ensure_ascii=True).lower()
            score = sum(1 for tok in tokens if tok in blob)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def save(self, path: Path) -> None:
        lines = [json.dumps(row, ensure_ascii=True) for row in self.entries]
        payload = "\n".join(lines)
        if payload:
            payload += "\n"
        path.write_text(payload)

    @classmethod
    def load(cls, path: Path) -> "MemoryStore":
        if not path.exists():
            return cls()
        text = path.read_text().strip()
        if not text:
            return cls()

        entries: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                entries.append(row)
        return cls(entries=entries)
