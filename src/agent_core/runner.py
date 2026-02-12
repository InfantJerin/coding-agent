from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_core.models import RunArtifact, RunResult, TaskRequest
from agent_core.tooling import ToolPolicy, ToolRegistry


def _pick_scope(question: str) -> str:
    q = question.lower()
    if any(tok in q for tok in ["amount", "maturity", "interest rate", "pricing"]):
        return "doc"
    if any(tok in q for tok in ["definition", "defined", "means"]):
        return "definition"
    if any(tok in q for tok in ["section", "covenant", "default", "maturity", "margin", "interest"]):
        return "section"
    return "doc"


def _candidate_terms(question: str) -> list[str]:
    tokens = re.findall(r"\b[A-Z][A-Za-z0-9\-]{2,}\b", question)
    return list(dict.fromkeys(tokens))[:4]


class GenericHeadlessAgent:
    def __init__(self, registry: ToolRegistry, policy: ToolPolicy) -> None:
        self.registry = registry
        self.policy = policy

    def _call_tool(self, trace: list[dict[str, Any]], tool_name: str, **kwargs: Any) -> Any:
        self.policy.check(tool_name)
        tool = self.registry.resolve(tool_name)
        entry: dict[str, Any] = {"tool": tool_name, "args": kwargs}
        try:
            output = tool.run(**kwargs)
            entry["ok"] = True
            entry["output_preview"] = str(output)[:500]
            trace.append(entry)
            return output
        except Exception as exc:  # pragma: no cover
            entry["ok"] = False
            entry["error"] = str(exc)
            trace.append(entry)
            raise

    def _bootstrap(self, trace: list[dict[str, Any]], documents: list[Path]) -> tuple[dict[str, Any], dict[str, Any]]:
        state: dict[str, Any] = {
            "scratchpad": {},
            "reading_trail": [],
            "open_questions": [],
        }
        document_store = self._call_tool(
            trace,
            "load_documents",
            documents=[str(doc) for doc in documents],
        )
        doc_map = self._call_tool(
            trace,
            "build_doc_map",
            document_store=document_store,
        )
        return state, doc_map

    def _ops_answer_question(
        self,
        trace: list[dict[str, Any]],
        state: dict[str, Any],
        doc_map: dict[str, Any],
        question: str,
    ) -> dict[str, Any]:
        scope = _pick_scope(question)

        hits = self._call_tool(
            trace,
            "search_in_doc",
            doc_map=doc_map,
            query=question,
            scope=scope,
            top_k=6,
        )

        anchors: list[str] = []
        for hit in hits[:3]:
            anchor = hit.get("anchor")
            if not anchor:
                continue
            anchors.append(anchor)
            self._call_tool(trace, "append_reading_trail", state=state, anchor=anchor)

            span = self._call_tool(trace, "read_span", doc_map=doc_map, anchor=anchor)
            refs = [
                ref
                for ref in doc_map.get("xrefs", [])
                if ref.get("from_anchor") == anchor and ref.get("ref_type") in {"section_ref", "definition_ref"}
            ]
            for ref in refs[:2]:
                followed = self._call_tool(trace, "follow_reference", doc_map=doc_map, ref_id=ref["id"])
                if followed.get("resolved"):
                    ref_anchor = followed["anchor"]
                    anchors.append(ref_anchor)
                    self._call_tool(trace, "append_reading_trail", state=state, anchor=ref_anchor)
                    self._call_tool(trace, "read_span", doc_map=doc_map, anchor=ref_anchor)
                else:
                    state["open_questions"].append(f"Unresolved reference: {ref.get('target_text')}")

            self._call_tool(
                trace,
                "write_scratchpad",
                state=state,
                key=f"hit:{anchor}",
                content={
                    "question": question,
                    "scope": scope,
                    "hit": hit,
                    "span": span,
                },
            )

        doc_id = doc_map["document_store"]["documents"][0]["doc_id"] if doc_map["document_store"]["documents"] else None
        if doc_id:
            for term in _candidate_terms(question):
                definition = self._call_tool(
                    trace,
                    "read_definition",
                    doc_map=doc_map,
                    term=term,
                    doc_id=doc_id,
                )
                if definition.get("found"):
                    d_anchor = definition["anchor"]
                    anchors.append(d_anchor)
                    self._call_tool(trace, "append_reading_trail", state=state, anchor=d_anchor)
                    self._call_tool(
                        trace,
                        "write_scratchpad",
                        state=state,
                        key=f"definition:{term}",
                        content=definition,
                    )

        unique_anchors = list(dict.fromkeys(anchors))
        evidence = self._call_tool(trace, "quote_evidence", doc_map=doc_map, anchors=unique_anchors)
        consistency = self._call_tool(trace, "consistency_check", claim=question, evidence=evidence)
        answer = self._call_tool(
            trace,
            "build_ops_answer",
            question=question,
            evidence=evidence,
            scratchpad=state.get("scratchpad", {}),
            consistency=consistency,
        )

        return {
            "question": question,
            "scope": scope,
            "answer": answer,
            "anchors": unique_anchors,
            "evidence": evidence,
            "consistency": consistency,
        }

    def run(self, task: TaskRequest, output_dir: Path) -> RunResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        trace: list[dict[str, Any]] = []

        state, doc_map = self._bootstrap(trace=trace, documents=task.documents)

        combined_text = "\n\n".join(
            page
            for doc in doc_map["document_store"]["documents"]
            for page in doc.get("pages", [])
        )
        extraction = self._call_tool(
            trace,
            "extract_finance_signals",
            text=combined_text,
            instruction=task.instruction,
            doc_map=doc_map,
            document_type=str(task.metadata.get("document_type", "") or "").strip() or None,
        )

        answers = [
            self._ops_answer_question(
                trace=trace,
                state=state,
                doc_map=doc_map,
                question=question,
            )
            for question in task.questions
        ]

        report_md = self._call_tool(
            trace,
            "build_summary_report",
            instruction=task.instruction,
            extraction=extraction,
            qa=[{"question": item["question"], "answer": item["answer"]} for item in answers],
        )

        artifacts: list[RunArtifact] = []

        if "report" in task.output_modes:
            report_path = output_dir / "summary_report.md"
            report_path.write_text(report_md)
            artifacts.append(RunArtifact(name="report", path=report_path))

        if "json" in task.output_modes:
            json_path = output_dir / "extraction.json"
            payload = {
                "extraction": extraction,
                "qa": answers,
                "reading_trail": state.get("reading_trail", []),
                "open_questions": state.get("open_questions", []),
                "doc_map_summary": {
                    "sections": len(doc_map.get("sections", [])),
                    "definitions": len(doc_map.get("definitions", [])),
                    "xrefs": len(doc_map.get("xrefs", [])),
                },
            }
            json_path.write_text(json.dumps(payload, indent=2))
            artifacts.append(RunArtifact(name="json", path=json_path))

        trace_path = output_dir / "run_trace.json"
        trace_path.write_text(json.dumps(trace, indent=2))
        artifacts.append(RunArtifact(name="trace", path=trace_path))

        run_info_path = output_dir / "run_result.json"
        run_info = {
            "success": True,
            "message": "Completed run",
            "artifacts": [{"name": a.name, "path": str(a.path)} for a in artifacts],
            "task": asdict(task),
        }
        run_info["task"]["documents"] = [str(p) for p in task.documents]
        run_info_path.write_text(json.dumps(run_info, indent=2))
        artifacts.append(RunArtifact(name="run_result", path=run_info_path))

        return RunResult(success=True, message="Completed run", artifacts=artifacts, trace=trace)

    def respond(self, instruction: str, documents: list[Path], query: str) -> tuple[str, list[dict[str, Any]]]:
        trace: list[dict[str, Any]] = []
        state, doc_map = self._bootstrap(trace=trace, documents=documents)

        combined_text = "\n\n".join(
            page
            for doc in doc_map["document_store"]["documents"]
            for page in doc.get("pages", [])
        )
        extraction = self._call_tool(
            trace,
            "extract_finance_signals",
            text=combined_text,
            instruction=instruction,
            doc_map=doc_map,
            document_type=None,
        )

        result = self._ops_answer_question(
            trace=trace,
            state=state,
            doc_map=doc_map,
            question=query,
        )

        lines: list[str] = []
        lines.append("## Answer")
        lines.append(result["answer"])
        lines.append("")
        lines.append("## Consistency")
        lines.append(str(result["consistency"]))
        lines.append("")
        lines.append("## Reading Trail")
        for anchor in state.get("reading_trail", [])[:20]:
            lines.append(f"- {anchor}")
        lines.append("")
        lines.append("## Open Questions")
        if state.get("open_questions"):
            for item in state["open_questions"][:20]:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")
        lines.append("## Extracted Signals")
        for key, values in extraction.get("signals", {}).items():
            lines.append(f"- {key}: {', '.join(values) if values else 'None detected'}")
        if extraction.get("field_extraction"):
            lines.append("")
            lines.append("## Extracted Terms")
            lines.append(f"- document_type: {extraction.get('document_type', 'unknown')}")
            consistency = extraction.get("consistency", {})
            lines.append(f"- consistency: {consistency.get('status')} ({consistency.get('score')})")
            for field_name, field_data in extraction.get("field_extraction", {}).items():
                value = field_data.get("value") or "Not found"
                lines.append(f"- {field_name}: {value}")

        return "\n".join(lines), trace
