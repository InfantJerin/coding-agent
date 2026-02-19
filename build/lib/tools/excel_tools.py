from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any


class ExtractTablesTool:
    name = "extract_tables"

    def run(self, doc_id: str, page_start: int, page_end: int,
            doc_map: dict[str, Any]) -> list[dict[str, Any]]:
        path = None
        for doc in doc_map.get("document_store", {}).get("documents", []):
            if doc["doc_id"] == doc_id:
                path = doc["path"]
                break
        if not path:
            raise ValueError(f"Unknown doc_id: {doc_id}")

        import pdfplumber
        results = []
        with pdfplumber.open(path) as pdf:
            for page_num in range(page_start, min(page_end + 1, len(pdf.pages) + 1)):
                page = pdf.pages[page_num - 1]
                for i, table in enumerate(page.extract_tables() or []):
                    if not table:
                        continue
                    results.append({
                        "page": page_num,
                        "table_index": i,
                        "anchor": f"{doc_id}:p{page_num}:table{i}",
                        "rows": table,
                        "row_count": len(table),
                        "col_count": max(len(r) for r in table) if table else 0,
                    })
        return results


class RunPythonTool:
    name = "run_python"

    def run(self, code: str, workspace_dir: str) -> dict[str, Any]:
        os.makedirs(workspace_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            script_path = f.name
        try:
            result = subprocess.run(
                ["python", script_path],
                capture_output=True, text=True, timeout=30, cwd=workspace_dir,
            )
            return {
                "stdout": result.stdout[:3000],
                "stderr": result.stderr[:500] or None,
                "returncode": result.returncode,
                "workspace_dir": workspace_dir,
            }
        finally:
            os.unlink(script_path)
