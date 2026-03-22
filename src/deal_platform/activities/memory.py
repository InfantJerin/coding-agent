from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from temporalio import activity

from deal_platform.context_registry.storage import LocalContextStore

_store = LocalContextStore()


@activity.defn
async def load_agent_memory(context_id: str) -> dict[str, Any]:
    """Load all agent memory files from local filesystem.

    Returns a dict matching AgentMemory fields (serialized).
    """
    memory_md = _store.load_memory_file(context_id, "MEMORY.md")
    extracted_terms_raw = _store.load_memory_file(context_id, "extracted_terms.json")
    gate_status_raw = _store.load_memory_file(context_id, "gate_status.json")
    state_raw = _store.load_memory_file(context_id, "state.json")

    # Parse JSONL files
    events: list[dict[str, Any]] = []
    events_raw = _store.load_memory_file(context_id, "events.jsonl")
    for line in events_raw.strip().splitlines():
        if line.strip():
            events.append(json.loads(line))

    decisions: list[dict[str, Any]] = []
    decisions_raw = _store.load_memory_file(context_id, "audit/decisions.jsonl")
    for line in decisions_raw.strip().splitlines():
        if line.strip():
            decisions.append(json.loads(line))

    return {
        "context_id": context_id,
        "memory_md": memory_md,
        "extracted_terms": json.loads(extracted_terms_raw) if extracted_terms_raw.strip() else {},
        "gate_status": json.loads(gate_status_raw) if gate_status_raw.strip() else {},
        "events": events,
        "state": json.loads(state_raw) if state_raw.strip() else {},
        "decisions": decisions,
    }


@activity.defn
async def save_agent_memory(context_id: str, memory: dict[str, Any]) -> None:
    """Save agent memory files to local filesystem.

    Overwrites MEMORY.md, extracted_terms.json, gate_status.json, state.json.
    Appends new entries to events.jsonl and audit/decisions.jsonl.
    """
    _store.save_memory_file(context_id, "MEMORY.md", memory.get("memory_md", ""))
    _store.save_memory_file(
        context_id,
        "extracted_terms.json",
        json.dumps(memory.get("extracted_terms", {}), indent=2),
    )
    _store.save_memory_file(
        context_id,
        "gate_status.json",
        json.dumps(memory.get("gate_status", {}), indent=2),
    )
    _store.save_memory_file(
        context_id,
        "state.json",
        json.dumps(memory.get("state", {}), indent=2),
    )

    # Append new events (compare against what's already on disk)
    existing_events_raw = _store.load_memory_file(context_id, "events.jsonl")
    existing_count = len([l for l in existing_events_raw.strip().splitlines() if l.strip()])
    new_events = memory.get("events", [])[existing_count:]
    for event in new_events:
        _store.append_memory_file(context_id, "events.jsonl", json.dumps(event))

    # Append new decisions
    existing_decisions_raw = _store.load_memory_file(context_id, "audit/decisions.jsonl")
    existing_dec_count = len([l for l in existing_decisions_raw.strip().splitlines() if l.strip()])
    new_decisions = memory.get("decisions", [])[existing_dec_count:]
    for decision in new_decisions:
        _store.append_memory_file(context_id, "audit/decisions.jsonl", json.dumps(decision))
