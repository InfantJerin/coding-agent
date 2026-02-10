from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TaskRequest:
    instruction: str
    documents: list[Path]
    questions: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=lambda: ["report", "json"])
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    tool: str
    ok: bool
    output: Any
    error: str | None = None


@dataclass
class RunArtifact:
    name: str
    path: Path


@dataclass
class RunResult:
    success: bool
    message: str
    artifacts: list[RunArtifact]
    trace: list[dict[str, Any]]
