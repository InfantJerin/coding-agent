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


@dataclass
class ExtractionEvidence:
    anchor: str
    excerpt: str


@dataclass
class ExtractionField:
    value: str | None
    found: bool
    confidence: float
    required: bool
    evidence: list[ExtractionEvidence] = field(default_factory=list)
    reason: str = ""
    unresolved_dependencies: list[str] = field(default_factory=list)


@dataclass
class ConsistencyResult:
    status: str
    score: float
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    session_id: str
    step_history: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    prompt_context: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    role: str   # "user" | "assistant"
    content: str
    at: str     # ISO timestamp
