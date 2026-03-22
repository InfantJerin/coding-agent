from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from deal_platform.context_registry.storage import LocalContextStore
from deal_platform.db.connection import DatabaseConnection
from deal_platform.db.schema import initialize_db
from deal_platform.models import ContextConfig


class ContextRegistry:
    """Manages deal context lifecycle: creation, lookup, status, and closure.

    Coordinates between:
    - LocalContextStore (filesystem: context.yaml + memory files)
    - SQLite (context_index for cross-context queries)
    - Temporal (workflow lifecycle — optional, injected when available)
    """

    def __init__(
        self,
        store: LocalContextStore | None = None,
        db: DatabaseConnection | None = None,
        temporal_client: Any | None = None,
    ):
        self.store = store or LocalContextStore()
        self.db = db or DatabaseConnection()
        self.temporal_client = temporal_client
        initialize_db(self.db)

    async def create_context(self, config: dict[str, Any]) -> str:
        """Create a new deal context.

        1. Generate context_id if not provided
        2. Write context.yaml and initialize memory files
        3. Insert row in context_index (SQLite)
        4. Start Temporal workflow if client is available

        Returns the context_id.
        """
        now = datetime.now(timezone.utc).isoformat()
        context_id = config.get("context_id") or f"deal-{uuid.uuid4().hex[:8]}"
        config["context_id"] = context_id
        config.setdefault("status", "active")
        config.setdefault("created_at", now)
        config.setdefault("name", context_id)

        # Write filesystem
        self.store.create(context_id, config)

        # Write to SQLite context_index
        conn = self.db.get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO context_index (context_id, name, status, created_at, created_by, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    context_id,
                    config.get("name", context_id),
                    config.get("status", "active"),
                    config.get("created_at", now),
                    config.get("created_by", ""),
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Start Temporal workflow if client available
        if self.temporal_client is not None:
            task_queue = config.get("temporal", {}).get("task_queue", "deal-agent-tasks")
            await self.temporal_client.start_workflow(
                "DealAgentWorkflow",
                context_id,
                id=context_id,
                task_queue=task_queue,
            )

        return context_id

    async def get_context(self, context_id: str) -> dict[str, Any] | None:
        """Load context config from filesystem."""
        return self.store.load_config(context_id)

    async def get_status(self, context_id: str) -> dict[str, Any]:
        """Query Temporal workflow for current status."""
        if self.temporal_client is None:
            # Fallback: return status from DB
            conn = self.db.get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM context_index WHERE context_id = ?",
                    (context_id,),
                ).fetchone()
                if row is None:
                    return {"context_id": context_id, "status": "not_found"}
                return dict(row)
            finally:
                conn.close()

        handle = self.temporal_client.get_workflow_handle(context_id)
        return await handle.query("get_status")

    async def list_contexts(self, status_filter: str | None = None) -> list[dict[str, Any]]:
        """List contexts from SQLite context_index."""
        conn = self.db.get_connection()
        try:
            if status_filter:
                rows = conn.execute(
                    "SELECT * FROM context_index WHERE status = ? ORDER BY created_at DESC",
                    (status_filter,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM context_index ORDER BY created_at DESC"
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    async def close_context(self, context_id: str) -> None:
        """Close a context: update status, signal workflow to finish."""
        now = datetime.now(timezone.utc).isoformat()

        # Update DB
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE context_index SET status = 'closed', updated_at = ? WHERE context_id = ?",
                (now, context_id),
            )
            conn.commit()
        finally:
            conn.close()

        # Update filesystem
        config = self.store.load_config(context_id)
        if config:
            config["status"] = "closed"
            self.store.save_config(context_id, config)

        # Signal Temporal workflow to close
        if self.temporal_client is not None:
            handle = self.temporal_client.get_workflow_handle(context_id)
            await handle.signal("on_event", {
                "event_id": f"evt-close-{uuid.uuid4().hex[:8]}",
                "context_id": context_id,
                "event_type": "close",
                "source": "registry",
                "timestamp": now,
                "payload": {},
            })
