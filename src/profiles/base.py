from __future__ import annotations

from dataclasses import dataclass

from agent_core.tooling import ToolPolicy, ToolRegistry


@dataclass
class AgentProfile:
    name: str
    registry: ToolRegistry
    policy: ToolPolicy
