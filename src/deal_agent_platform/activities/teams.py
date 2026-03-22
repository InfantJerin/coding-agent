from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TeamsActivities:
    """Scaffold for outbound communication activities."""

    messages: list[dict[str, Any]] = field(default_factory=list)

    def post_progress(self, *, channel_id: str, message: str) -> str:
        msg = {
            "type": "progress",
            "channel_id": channel_id,
            "message": message,
        }
        self.messages.append(msg)
        return f"msg-{len(self.messages)}"

    def post_approval_request(self, *, channel_id: str, request: dict[str, Any]) -> str:
        msg = {
            "type": "approval_request",
            "channel_id": channel_id,
            "request": request,
        }
        self.messages.append(msg)
        return f"approval-{len(self.messages)}"

    def escalate_approval(self, *, channel_id: str, request: dict[str, Any]) -> str:
        msg = {
            "type": "approval_escalation",
            "channel_id": channel_id,
            "request": request,
        }
        self.messages.append(msg)
        return f"escalation-{len(self.messages)}"
