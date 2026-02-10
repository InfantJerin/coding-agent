from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


class SafeBashTool:
    name = "safe_bash"

    _allowed_prefixes = {
        "rg",
        "cat",
        "sed",
        "awk",
        "head",
        "tail",
        "wc",
        "cut",
        "sort",
        "uniq",
    }

    def run(self, command: str, cwd: str | None = None, timeout_sec: int = 15) -> str:
        parts = shlex.split(command)
        if not parts:
            raise ValueError("Empty command")
        if parts[0] not in self._allowed_prefixes:
            raise PermissionError(f"Command prefix '{parts[0]}' is not allowed")

        workdir = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        completed = subprocess.run(
            parts,
            cwd=workdir,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"Command failed: {command}")
        return completed.stdout
