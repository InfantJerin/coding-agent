from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from deal_platform.activities.context import load_context_config
    from deal_platform.activities.extraction import extract_terms
    from deal_platform.activities.memory import load_agent_memory, save_agent_memory
    from deal_platform.activities.transactional import db_read, db_write

TASK_QUEUE = "deal-agent-tasks"
CONTINUE_AS_NEW_THRESHOLD = 10_000


@workflow.defn
class DealAgentWorkflow:
    """One workflow per deal context. Receives events as Signals, processes them
    as Activities, evaluates readiness gates, and persists memory.

    Lifecycle: wake on event -> load memory -> process -> save memory -> sleep.
    """

    def __init__(self) -> None:
        self._pending_events: list[dict[str, Any]] = []
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._extracted_terms: dict[str, dict[str, Any]] = {}
        self._gate_status: dict[str, dict[str, Any]] = {}
        self._config: dict[str, Any] = {}
        self._history_length: int = 0
        self._last_activity: str = ""
        self._closing: bool = False

    # ── Signal Handlers ──

    @workflow.signal
    async def on_event(self, event: dict[str, Any]) -> None:
        """Channel Bridge or CLI sends events here."""
        self._pending_events.append(event)

    @workflow.signal
    async def on_approval_response(self, response: dict[str, Any]) -> None:
        """Teams bot or CLI sends approval responses here."""
        request_id = response.get("request_id", "")
        if request_id in self._pending_approvals:
            self._pending_approvals[request_id]["response"] = response

    # ── Query Handler ──

    @workflow.query
    def get_status(self) -> dict[str, Any]:
        """Dashboard reads state without waking the agent."""
        return {
            "pending_events": len(self._pending_events),
            "pending_approvals": {
                k: {"has_response": "response" in v}
                for k, v in self._pending_approvals.items()
            },
            "extracted_terms_count": len(self._extracted_terms),
            "gate_status": self._gate_status,
            "history_length": self._history_length,
            "last_activity": self._last_activity,
            "closing": self._closing,
        }

    # ── Main Loop ──

    @workflow.run
    async def run(self, context_id: str) -> None:
        # Step 1: Load config
        self._config = await workflow.execute_activity(
            load_context_config,
            context_id,
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Step 2: Load memory and restore state
        memory = await workflow.execute_activity(
            load_agent_memory,
            context_id,
            start_to_close_timeout=timedelta(seconds=30),
        )
        self._extracted_terms = memory.get("extracted_terms", {})
        self._gate_status = memory.get("gate_status", {})
        all_events: list[dict[str, Any]] = memory.get("events", [])
        all_decisions: list[dict[str, Any]] = memory.get("decisions", [])

        # Step 3: Main event loop
        while not self._closing:
            # Wait for events (zero compute)
            await workflow.wait_condition(lambda: len(self._pending_events) > 0)

            # Drain pending events
            batch = self._pending_events[:]
            self._pending_events.clear()

            for event in batch:
                event_type = event.get("event_type", "")

                # Handle close signal
                if event_type == "close":
                    self._closing = True
                    break

                # Record event
                all_events.append(event)
                self._last_activity = workflow.now().isoformat()

                # ANALYST: Extract terms from documents
                if event_type in ("document_received", "manual_trigger"):
                    new_terms = await workflow.execute_activity(
                        extract_terms,
                        args=[context_id, event.get("payload", {})],
                        start_to_close_timeout=timedelta(minutes=5),
                    )
                    # Merge extracted terms (last-write-wins with previous tracking)
                    for field_name, term_data in new_terms.items():
                        existing = self._extracted_terms.get(field_name)
                        if existing and existing.get("value") != term_data.get("value"):
                            term_data["previous"] = {
                                "value": existing.get("value"),
                                "source": existing.get("source"),
                            }
                        self._extracted_terms[field_name] = term_data

                    # Write extracted terms to transactional DB
                    for field_name, term_data in new_terms.items():
                        await workflow.execute_activity(
                            db_write,
                            args=[
                                context_id,
                                "extracted_terms",
                                {
                                    "field_name": field_name,
                                    "value": str(term_data.get("value", "")),
                                    "source": term_data.get("source", ""),
                                },
                            ],
                            start_to_close_timeout=timedelta(seconds=15),
                        )

                # OBSERVER: Evaluate readiness gates
                self._evaluate_gates()

            # Step 4: Save memory
            memory_bundle = {
                "context_id": context_id,
                "memory_md": self._build_memory_md(context_id),
                "extracted_terms": self._extracted_terms,
                "gate_status": self._gate_status,
                "events": all_events,
                "state": {
                    "history_length": self._history_length,
                    "last_activity": self._last_activity,
                },
                "decisions": all_decisions,
            }
            await workflow.execute_activity(
                save_agent_memory,
                args=[context_id, memory_bundle],
                start_to_close_timeout=timedelta(seconds=30),
            )

            # Step 5: Check history size for continue_as_new
            self._history_length += len(batch)
            if self._history_length > CONTINUE_AS_NEW_THRESHOLD:
                workflow.continue_as_new(context_id)

    # ── Gate Evaluation ──

    def _evaluate_gates(self) -> None:
        """Evaluate all readiness gates against current extracted terms."""
        gates_config = self._config.get("readiness_gates", {})

        for gate_name, gate_def in gates_config.items():
            # Skip already satisfied gates
            existing = self._gate_status.get(gate_name, {})
            if existing.get("satisfied"):
                continue

            required_fields = gate_def.get("requires_fields", [])
            required_gates = gate_def.get("requires_gates", [])

            # Check field requirements
            missing_fields = [
                f for f in required_fields if f not in self._extracted_terms
            ]

            # Check gate dependencies (DAG)
            missing_gates = [
                g
                for g in required_gates
                if not self._gate_status.get(g, {}).get("satisfied")
            ]

            if not missing_fields and not missing_gates:
                self._gate_status[gate_name] = {
                    "gate_name": gate_name,
                    "satisfied": True,
                    "satisfied_at": workflow.now().isoformat(),
                    "missing_fields": [],
                    "missing_gates": [],
                }
                workflow.logger.info(
                    f"Gate '{gate_name}' satisfied — triggers: {gate_def.get('triggers', 'none')}"
                )
            else:
                self._gate_status[gate_name] = {
                    "gate_name": gate_name,
                    "satisfied": False,
                    "satisfied_at": None,
                    "missing_fields": missing_fields,
                    "missing_gates": missing_gates,
                }

    # ── Memory Markdown ──

    def _build_memory_md(self, context_id: str) -> str:
        """Build a human-readable MEMORY.md from current state."""
        lines = [f"# {self._config.get('name', context_id)}", ""]

        lines.append("## Extracted Terms")
        if self._extracted_terms:
            for name, term in sorted(self._extracted_terms.items()):
                val = term.get("value", "")
                src = term.get("source", "unknown")
                lines.append(f"- **{name}**: {val} (from {src})")
        else:
            lines.append("- No terms extracted yet")
        lines.append("")

        lines.append("## Gate Status")
        if self._gate_status:
            for name, status in sorted(self._gate_status.items()):
                if status.get("satisfied"):
                    lines.append(f"- [x] {name} — satisfied at {status.get('satisfied_at', '?')}")
                else:
                    missing = status.get("missing_fields", [])
                    lines.append(f"- [ ] {name} — waiting on: {', '.join(missing) if missing else 'gate deps'}")
        else:
            lines.append("- No gates configured")
        lines.append("")

        return "\n".join(lines)
