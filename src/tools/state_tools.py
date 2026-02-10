from __future__ import annotations

from typing import Any


class WriteScratchpadTool:
    name = "write_scratchpad"

    def run(self, state: dict[str, Any], key: str, content: Any) -> dict[str, Any]:
        state.setdefault("scratchpad", {})[key] = content
        return {"ok": True, "key": key}


class ReadScratchpadTool:
    name = "read_scratchpad"

    def run(self, state: dict[str, Any], key: str) -> dict[str, Any]:
        return {"key": key, "value": state.get("scratchpad", {}).get(key)}


class AppendReadingTrailTool:
    name = "append_reading_trail"

    def run(self, state: dict[str, Any], anchor: str) -> dict[str, Any]:
        trail = state.setdefault("reading_trail", [])
        if anchor not in trail:
            trail.append(anchor)
        return {"ok": True, "reading_trail_len": len(trail)}
