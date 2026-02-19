from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class Tool(Protocol):
    name: str

    def run(self, **kwargs: Any) -> Any:
        ...


@dataclass
class ToolRegistry:
    tools: dict[str, Tool]

    def resolve(self, name: str) -> Tool:
        if name not in self.tools:
            raise KeyError(f"Tool '{name}' is not registered")
        return self.tools[name]


def _compile_pattern(pattern: str) -> re.Pattern[str]:
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.compile(rf"^{escaped}$")


@dataclass
class ToolPolicy:
    allow: list[str] | None = None
    deny: list[str] | None = None

    def _matches(self, tool_name: str, patterns: list[str]) -> bool:
        return any(_compile_pattern(pattern).match(tool_name) for pattern in patterns)

    def check(self, tool_name: str) -> None:
        normalized = tool_name.strip()
        deny = self.deny or []
        allow = self.allow or ["*"]

        if self._matches(normalized, deny):
            raise PermissionError(f"Tool '{tool_name}' is denied by policy")
        if not self._matches(normalized, allow):
            raise PermissionError(f"Tool '{tool_name}' is not allowed by policy")

    def merged(self, override: "ToolPolicy | None" = None) -> "ToolPolicy":
        if override is None:
            return ToolPolicy(allow=list(self.allow or ["*"]), deny=list(self.deny or []))

        base_allow = list(self.allow or ["*"])
        base_deny = list(self.deny or [])
        over_allow = list(override.allow or ["*"])
        over_deny = list(override.deny or [])

        # Explicit task-level allow narrows accessible tools.
        if over_allow == ["*"]:
            allow = base_allow
        elif base_allow == ["*"]:
            allow = over_allow
        else:
            allow = [item for item in base_allow if item in set(over_allow)]
        # Deny always wins and composes additively.
        deny = sorted(set(base_deny + over_deny))
        return ToolPolicy(allow=allow, deny=deny)
