from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_core.memory import MemoryStore
from agent_core.models import RunArtifact, RunResult, SessionState, TaskRequest
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

    @staticmethod
    def _utc_now_iso() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _emit_event(self, trace: list[dict[str, Any]], state: SessionState, event: str, payload: dict[str, Any]) -> None:
        row = {
            "event": event,
            "at": self._utc_now_iso(),
            "session_id": state.session_id,
            **payload,
        }
        trace.append(row)
        state.step_history.append(row)

    def _checkpoint(
        self,
        trace: list[dict[str, Any]],
        state: SessionState,
        *,
        step: str,
        run_state: dict[str, Any],
    ) -> None:
        cp = {
            "step": step,
            "at": self._utc_now_iso(),
            "state": {
                "reading_trail_size": len(run_state.get("reading_trail", [])),
                "open_questions_size": len(run_state.get("open_questions", [])),
                "scratchpad_keys": sorted(list(run_state.get("scratchpad", {}).keys()))[:20],
            },
        }
        state.checkpoints.append(cp)
        self._emit_event(trace, state, "checkpoint", cp)

    def _build_prompt_context(
        self,
        *,
        instruction: str,
        doc_map: dict[str, Any],
        metadata: dict[str, Any],
        policy: ToolPolicy,
    ) -> dict[str, Any]:
        return {
            "instruction": instruction,
            "document_type": metadata.get("document_type") or "credit_agreement",
            "skill_pack": metadata.get("skill_pack") or "finance-docs",
            "tooling": {
                "allow": policy.allow or ["*"],
                "deny": policy.deny or [],
                "available_tools": sorted(self.registry.tools.keys()),
            },
            "doc_map_summary": {
                "documents": len(doc_map.get("document_store", {}).get("documents", [])),
                "sections": len(doc_map.get("sections", [])),
                "definitions": len(doc_map.get("definitions", [])),
                "xrefs": len(doc_map.get("xrefs", [])),
            },
        }

    def _resolve_policy(self, metadata: dict[str, Any] | None) -> ToolPolicy:
        metadata = metadata or {}
        override = metadata.get("tool_policy_override", {})
        if not isinstance(override, dict):
            return self.policy
        allow = override.get("allow")
        deny = override.get("deny")
        if allow is None and deny is None:
            return self.policy
        return self.policy.merged(ToolPolicy(allow=allow, deny=deny))

    def _validate_extraction(self, extraction: dict[str, Any]) -> None:
        required = {"instruction", "signals", "document_type", "schema_version", "field_extraction", "consistency"}
        missing = sorted(required - set(extraction.keys()))
        if missing:
            raise ValueError(f"Extraction missing required keys: {missing}")
        consistency = extraction.get("consistency", {})
        if not isinstance(consistency, dict):
            raise ValueError("Extraction consistency block must be an object")
        if consistency.get("status") not in {"passed", "warning", "failed", "skipped"}:
            raise ValueError(f"Unexpected consistency status: {consistency.get('status')}")

    def _call_tool(
        self,
        trace: list[dict[str, Any]],
        session_state: SessionState,
        policy: ToolPolicy,
        tool_name: str,
        **kwargs: Any,
    ) -> Any:
        policy.check(tool_name)
        tool = self.registry.resolve(tool_name)
        self._emit_event(trace, session_state, "tool_started", {"tool": tool_name, "args": kwargs})
        entry: dict[str, Any] = {"tool": tool_name, "args": kwargs}
        try:
            output = tool.run(**kwargs)
            entry["ok"] = True
            entry["output_preview"] = str(output)[:500]
            trace.append(entry)
            self._emit_event(trace, session_state, "tool_finished", {"tool": tool_name, "ok": True})
            return output
        except Exception as exc:  # pragma: no cover
            entry["ok"] = False
            entry["error"] = str(exc)
            trace.append(entry)
            self._emit_event(trace, session_state, "tool_finished", {"tool": tool_name, "ok": False, "error": str(exc)})
            raise

    def _bootstrap(
        self,
        trace: list[dict[str, Any]],
        session: SessionState,
        policy: ToolPolicy,
        documents: list[Path],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        state: dict[str, Any] = {
            "scratchpad": {},
            "reading_trail": [],
            "open_questions": [],
        }
        document_store = self._call_tool(
            trace,
            session,
            policy,
            "load_documents",
            documents=[str(doc) for doc in documents],
        )
        doc_map = self._call_tool(
            trace,
            session,
            policy,
            "build_doc_map",
            document_store=document_store,
        )
        return state, doc_map

    def _ops_answer_question(
        self,
        trace: list[dict[str, Any]],
        session: SessionState,
        policy: ToolPolicy,
        state: dict[str, Any],
        doc_map: dict[str, Any],
        memory: MemoryStore,
        question: str,
    ) -> dict[str, Any]:
        scope = _pick_scope(question)
        memory_hits = memory.query(question, top_k=3)
        if memory_hits:
            state["scratchpad"]["memory_hints"] = memory_hits

        hits = self._call_tool(
            trace,
            session,
            policy,
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
            self._call_tool(trace, session, policy, "append_reading_trail", state=state, anchor=anchor)

            span = self._call_tool(trace, session, policy, "read_span", doc_map=doc_map, anchor=anchor)
            refs = [
                ref
                for ref in doc_map.get("xrefs", [])
                if ref.get("from_anchor") == anchor and ref.get("ref_type") in {"section_ref", "definition_ref"}
            ]
            for ref in refs[:2]:
                followed = self._call_tool(trace, session, policy, "follow_reference", doc_map=doc_map, ref_id=ref["id"])
                if followed.get("resolved"):
                    ref_anchor = followed["anchor"]
                    anchors.append(ref_anchor)
                    self._call_tool(trace, session, policy, "append_reading_trail", state=state, anchor=ref_anchor)
                    self._call_tool(trace, session, policy, "read_span", doc_map=doc_map, anchor=ref_anchor)
                else:
                    state["open_questions"].append(f"Unresolved reference: {ref.get('target_text')}")

            self._call_tool(
                trace,
                session,
                policy,
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
                    session,
                    policy,
                    "read_definition",
                    doc_map=doc_map,
                    term=term,
                    doc_id=doc_id,
                )
                if definition.get("found"):
                    d_anchor = definition["anchor"]
                    anchors.append(d_anchor)
                    self._call_tool(trace, session, policy, "append_reading_trail", state=state, anchor=d_anchor)
                    self._call_tool(
                        trace,
                        session,
                        policy,
                        "write_scratchpad",
                        state=state,
                        key=f"definition:{term}",
                        content=definition,
                    )

        unique_anchors = list(dict.fromkeys(anchors))
        evidence = self._call_tool(trace, session, policy, "quote_evidence", doc_map=doc_map, anchors=unique_anchors)
        consistency = self._call_tool(trace, session, policy, "consistency_check", claim=question, evidence=evidence)
        answer = self._call_tool(
            trace,
            session,
            policy,
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
            "memory_hits": memory_hits,
        }

    def run(self, task: TaskRequest, output_dir: Path) -> RunResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        trace: list[dict[str, Any]] = []
        session = SessionState(session_id=f"s-{uuid.uuid4().hex[:10]}")
        run_policy = self._resolve_policy(task.metadata)
        memory_store = MemoryStore()

        self._emit_event(trace, session, "run_started", {"documents": [str(item) for item in task.documents]})
        state, doc_map = self._bootstrap(trace=trace, session=session, policy=run_policy, documents=task.documents)
        self._checkpoint(trace, session, step="bootstrap", run_state=state)
        session.prompt_context = self._build_prompt_context(
            instruction=task.instruction,
            doc_map=doc_map,
            metadata=task.metadata,
            policy=run_policy,
        )

        combined_text = "\n\n".join(
            page
            for doc in doc_map["document_store"]["documents"]
            for page in doc.get("pages", [])
        )
        extraction = self._call_tool(
            trace,
            session,
            run_policy,
            "extract_finance_signals",
            text=combined_text,
            instruction=task.instruction,
            doc_map=doc_map,
            document_type=str(task.metadata.get("document_type", "") or "").strip() or None,
        )
        self._validate_extraction(extraction)
        memory_store.add(kind="extraction", content={"document_type": extraction.get("document_type"), "field_extraction": extraction.get("field_extraction", {})})
        self._checkpoint(trace, session, step="extraction", run_state=state)

        answers = [
            self._ops_answer_question(
                trace=trace,
                session=session,
                policy=run_policy,
                state=state,
                doc_map=doc_map,
                memory=memory_store,
                question=question,
            )
            for question in task.questions
        ]
        for item in answers:
            memory_store.add(kind="qa", content={"question": item.get("question"), "answer": item.get("answer"), "anchors": item.get("anchors", [])})
        self._checkpoint(trace, session, step="qa", run_state=state)

        report_md = self._call_tool(
            trace,
            session,
            run_policy,
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
                "warnings": extraction.get("consistency", {}).get("warnings", []),
                "session": asdict(session),
                "memory_hits": memory_store.query(" ".join(task.questions), top_k=10),
                "doc_map_summary": {
                    "sections": len(doc_map.get("sections", [])),
                    "definitions": len(doc_map.get("definitions", [])),
                    "xrefs": len(doc_map.get("xrefs", [])),
                },
            }
            json_path.write_text(json.dumps(payload, indent=2))
            artifacts.append(RunArtifact(name="json", path=json_path))

        run_info_path = output_dir / "run_result.json"
        run_info = {
            "success": True,
            "message": "Completed run",
            "artifacts": [{"name": a.name, "path": str(a.path)} for a in artifacts],
            "task": asdict(task),
            "session_id": session.session_id,
        }
        run_info["task"]["documents"] = [str(p) for p in task.documents]
        run_info_path.write_text(json.dumps(run_info, indent=2))
        artifacts.append(RunArtifact(name="run_result", path=run_info_path))
        memory_store.save(output_dir / "memory.json")
        artifacts.append(RunArtifact(name="memory", path=output_dir / "memory.json"))
        self._emit_event(trace, session, "run_finished", {"success": True})
        trace_path = output_dir / "run_trace.json"
        trace_path.write_text(json.dumps(trace, indent=2))
        artifacts.append(RunArtifact(name="trace", path=trace_path))

        return RunResult(success=True, message="Completed run", artifacts=artifacts, trace=trace)

    def respond(
        self,
        instruction: str,
        documents: list[Path],
        query: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        trace: list[dict[str, Any]] = []
        session = SessionState(session_id=f"s-{uuid.uuid4().hex[:10]}")
        run_policy = self._resolve_policy(metadata)
        memory_store = MemoryStore()
        self._emit_event(trace, session, "respond_started", {"query": query})
        state, doc_map = self._bootstrap(trace=trace, session=session, policy=run_policy, documents=documents)
        session.prompt_context = self._build_prompt_context(
            instruction=instruction,
            doc_map=doc_map,
            metadata=metadata or {},
            policy=run_policy,
        )

        combined_text = "\n\n".join(
            page
            for doc in doc_map["document_store"]["documents"]
            for page in doc.get("pages", [])
        )
        extraction = self._call_tool(
            trace,
            session,
            run_policy,
            "extract_finance_signals",
            text=combined_text,
            instruction=instruction,
            doc_map=doc_map,
            document_type=str((metadata or {}).get("document_type", "")).strip() or None,
        )
        self._validate_extraction(extraction)
        memory_store.add(kind="extraction", content={"document_type": extraction.get("document_type"), "field_extraction": extraction.get("field_extraction", {})})

        result = self._ops_answer_question(
            trace=trace,
            session=session,
            policy=run_policy,
            state=state,
            doc_map=doc_map,
            memory=memory_store,
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
        lines.append("")
        lines.append("## Session")
        lines.append(f"- session_id: {session.session_id}")
        lines.append(f"- checkpoints: {len(session.checkpoints)}")

        self._emit_event(trace, session, "respond_finished", {"success": True})
        return "\n".join(lines), trace
