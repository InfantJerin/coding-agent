from __future__ import annotations

import datetime as dt
import re
from typing import Any

from agent_core.models import ConsistencyResult, ExtractionEvidence, ExtractionField
from llm.providers import LLMClient
from schemas.finance_registry import list_document_types, resolve_schema


class ExtractFinanceSignalsTool:
    name = "extract_finance_signals"

    _patterns = {
        "facility_amount": re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|m)?", re.IGNORECASE),
        "interest_terms": re.compile(r"(?:SOFR|LIBOR|prime rate|base rate|margin|spread|interest rate)", re.IGNORECASE),
        "covenants": re.compile(
            r"(?:leverage ratio|interest coverage ratio|fixed charge coverage|minimum liquidity|debt service)",
            re.IGNORECASE,
        ),
        "events_of_default": re.compile(r"events? of default|default", re.IGNORECASE),
        "maturity": re.compile(r"maturity date|termination date|expires? on", re.IGNORECASE),
    }

    def _resolve_doc_type(self, instruction: str, text: str, document_type: str | None) -> str:
        known_types = list_document_types()
        if document_type and document_type in known_types:
            return document_type
        hay = f"{instruction}\n{text}".lower()
        if "compliance certificate" in hay:
            return "compliance_certificate"
        if "rate notice" in hay:
            return "rate_notice"
        return "credit_agreement"

    def _match_score(self, haystack: str, needles: list[str]) -> int:
        low = haystack.lower()
        return sum(1 for needle in needles if needle.lower() in low)

    def _find_sections(self, doc_map: dict[str, Any], hints: list[str], limit: int = 4) -> list[dict[str, Any]]:
        ranked: list[tuple[int, dict[str, Any]]] = []
        for section in doc_map.get("sections", []):
            hay = " ".join(
                [
                    str(section.get("section_no", "")),
                    str(section.get("title", "")),
                    str(section.get("summary", "")),
                    " ".join(section.get("key_events", [])),
                ]
            )
            score = self._match_score(hay, hints)
            if score > 0:
                ranked.append((score, section))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [row[1] for row in ranked[:limit]]

    def _collect_blocks(self, doc_map: dict[str, Any], section: dict[str, Any], cap: int = 60) -> list[dict[str, Any]]:
        doc_id = section.get("doc_id")
        start = int(section.get("page_start", 1))
        end = int(section.get("page_end", start))
        out: list[dict[str, Any]] = []
        rows: list[tuple[int, int, str, str]] = []
        for anchor, data in doc_map.get("anchors", {}).items():
            if data.get("doc_id") != doc_id:
                continue
            page = int(data.get("page", 0))
            block = int(data.get("block", 0))
            if start <= page <= end:
                rows.append((page, block, anchor, str(data.get("text", ""))))
        rows.sort(key=lambda row: (row[0], row[1]))
        for page, _, anchor, text in rows[:cap]:
            out.append({"anchor": anchor, "page": page, "text": text})
        return out

    def _extract_from_pattern(self, pattern: str | None, blocks: list[dict[str, Any]]) -> str | None:
        if not pattern:
            return None
        rx = re.compile(pattern, re.IGNORECASE)
        for block in blocks:
            m = rx.search(block["text"])
            if m:
                if m.lastindex:
                    return (m.group(1) or "").strip()
                return m.group(0).strip()
        return None

    def _extract_best_snippet(self, blocks: list[dict[str, Any]], hints: list[str]) -> str | None:
        if not blocks:
            return None
        ranked: list[tuple[int, str]] = []
        for block in blocks:
            line = block["text"].strip()
            if not line:
                continue
            ranked.append((self._match_score(line, hints), line))
        ranked.sort(key=lambda row: row[0], reverse=True)
        best = ranked[0][1] if ranked else ""
        return best[:280] if best else None

    def _parse_date(self, value: str | None) -> dt.date | None:
        if not value:
            return None
        cleaned = value.strip()
        for fmt in ("%B %d, %Y", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
        return None

    def _validate_contract(
        self,
        *,
        extraction: dict[str, Any],
        schema: dict[str, Any],
        field_rows: dict[str, ExtractionField],
        consistency: ConsistencyResult,
    ) -> None:
        required_keys = {"instruction", "signals", "document_type", "schema_version", "field_extraction", "consistency"}
        missing = sorted(required_keys - set(extraction.keys()))
        if missing:
            raise ValueError(f"Invalid extraction payload. Missing keys: {missing}")

        schema_field_names = {str(field["name"]) for field in schema.get("fields", [])}
        payload_field_names = set(field_rows.keys())
        unexpected = sorted(payload_field_names - schema_field_names)
        if unexpected:
            raise ValueError(f"Extraction has fields not in schema: {unexpected}")

        for field_name, field in field_rows.items():
            if not 0.0 <= field.confidence <= 1.0:
                raise ValueError(f"Invalid confidence for field '{field_name}': {field.confidence}")
            if field.found and not field.evidence:
                consistency.warnings.append(f"Field '{field_name}' is found but has no evidence anchors")

        if consistency.status not in {"passed", "warning", "failed", "skipped"}:
            raise ValueError(f"Invalid consistency status: {consistency.status}")

    def run(
        self,
        text: str,
        instruction: str,
        doc_map: dict[str, Any] | None = None,
        document_type: str | None = None,
    ) -> dict[str, Any]:
        extraction: dict[str, Any] = {
            "instruction": instruction,
            "signals": {},
        }
        for key, pattern in self._patterns.items():
            matches = pattern.findall(text)
            extraction["signals"][key] = sorted(set(m.strip() for m in matches if m.strip()))[:25]

        doc_type = self._resolve_doc_type(instruction=instruction, text=text, document_type=document_type)
        _, schema = resolve_schema(doc_type)
        extraction["document_type"] = doc_type
        extraction["schema_version"] = schema["version"]

        if not doc_map:
            extraction["structure_pass"] = {"section_families": {}}
            extraction["field_extraction"] = {}
            extraction["consistency"] = {"status": "skipped", "score": 0.0, "issues": ["No document map provided"], "warnings": []}
            return extraction

        # Pass 1: discover structure families from section/page index.
        section_families: dict[str, list[dict[str, Any]]] = {}
        for field in schema["fields"]:
            sections = self._find_sections(doc_map=doc_map, hints=field["section_hints"])
            section_families[field["name"]] = [
                {
                    "section_no": sec.get("section_no"),
                    "title": sec.get("title"),
                    "anchor": sec.get("anchor"),
                    "page_start": sec.get("page_start"),
                    "page_end": sec.get("page_end"),
                }
                for sec in sections
            ]
        extraction["structure_pass"] = {"section_families": section_families}

        # Pass 2: field extraction with definitions and section context.
        field_rows: dict[str, ExtractionField] = {}
        for field in schema["fields"]:
            name = field["name"]
            sections = self._find_sections(doc_map=doc_map, hints=field["section_hints"])
            blocks: list[dict[str, Any]] = []
            for section in sections:
                blocks.extend(self._collect_blocks(doc_map=doc_map, section=section))

            for definition in doc_map.get("definitions", []):
                term = str(definition.get("term", ""))
                if self._match_score(term, field["term_hints"]) > 0:
                    blocks.append(
                        {
                            "anchor": definition.get("anchor", ""),
                            "page": None,
                            "text": f'{term} means {definition.get("text", "")}',
                        }
                    )

            scored: list[tuple[int, dict[str, Any]]] = []
            for block in blocks:
                score = self._match_score(block["text"], field["term_hints"])
                if field.get("pattern") and re.search(field["pattern"], block["text"], re.IGNORECASE):
                    score += 2
                if score > 0:
                    scored.append((score, block))
            scored.sort(key=lambda row: row[0], reverse=True)
            ranked_blocks = [row[1] for row in scored[:8]]

            value = self._extract_from_pattern(pattern=field.get("pattern"), blocks=ranked_blocks)
            if not value:
                value = self._extract_best_snippet(blocks=ranked_blocks, hints=field["term_hints"])

            evidence: list[ExtractionEvidence] = []
            seen = set()
            for row in ranked_blocks[:3]:
                anchor = row.get("anchor", "")
                if anchor and anchor not in seen:
                    seen.add(anchor)
                    evidence.append(ExtractionEvidence(anchor=anchor, excerpt=row["text"][:220]))
            top_score = scored[0][0] if scored else 0

            unresolved_dependencies = [] if value else ["missing_indexed_evidence"]
            field_rows[name] = ExtractionField(
                value=value,
                found=bool(value),
                confidence=round(min(1.0, top_score / 6), 3),
                required=bool(field.get("required")),
                evidence=evidence,
                reason=(
                    "Extracted from section-indexed evidence and definition context."
                    if value
                    else "No matching evidence found in indexed sections/definitions."
                ),
                unresolved_dependencies=unresolved_dependencies,
            )
        extraction["field_extraction"] = {
            field_name: {
                "value": field.value,
                "found": field.found,
                "confidence": field.confidence,
                "required": field.required,
                "evidence": [{"anchor": item.anchor, "excerpt": item.excerpt} for item in field.evidence],
                "reason": field.reason,
                "unresolved_dependencies": field.unresolved_dependencies,
            }
            for field_name, field in field_rows.items()
        }

        # Pass 3: consistency checks.
        issues: list[str] = []
        required = [field["name"] for field in schema["fields"] if field.get("required")]
        for key in required:
            row = field_rows.get(key)
            if not row or not row.found:
                issues.append(f"Missing required field: {key}")

        maturity_date = self._parse_date(field_rows.get("maturity_date").value if field_rows.get("maturity_date") else None)
        reporting_date = self._parse_date(field_rows.get("reporting_period_end").value if field_rows.get("reporting_period_end") else None)
        if maturity_date and reporting_date and maturity_date < reporting_date:
            issues.append("maturity_date is earlier than reporting_period_end")

        raw_amount = str(field_rows.get("facility_amount").value if field_rows.get("facility_amount") else "")
        if raw_amount and "$" not in raw_amount:
            issues.append("facility_amount did not include explicit currency symbol")

        found_count = sum(1 for row in field_rows.values() if row.found)
        coverage = found_count / max(1, len(field_rows))
        if issues:
            status = "warning"
            score = max(0.0, round(coverage - 0.2, 4))
        else:
            status = "passed"
            score = round(coverage, 4)
        consistency = ConsistencyResult(status=status, score=score, issues=issues, warnings=[])
        extraction["consistency"] = {
            "status": consistency.status,
            "score": consistency.score,
            "issues": consistency.issues,
            "warnings": consistency.warnings,
        }
        self._validate_contract(extraction=extraction, schema=schema, field_rows=field_rows, consistency=consistency)
        extraction["consistency"] = {
            "status": consistency.status,
            "score": consistency.score,
            "issues": consistency.issues,
            "warnings": consistency.warnings,
        }

        return extraction


class BuildOpsAnswerTool:
    name = "build_ops_answer"

    def __init__(self, llm_client: LLMClient | None = None, model_label: str | None = None) -> None:
        self.llm_client = llm_client
        self.model_label = model_label

    def _fallback(self, question: str, evidence: list[dict[str, Any]], consistency: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append(f"Question: {question}")
        lines.append("Answer basis (evidence):")
        for item in evidence[:6]:
            lines.append(
                f"- [{item.get('anchor')}] (p{item.get('page')}) {item.get('excerpt', '')[:220]}"
            )
        lines.append(f"Consistency: {consistency.get('status')} ({consistency.get('score')})")
        return "\n".join(lines)

    def run(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        scratchpad: dict[str, Any],
        consistency: dict[str, Any],
    ) -> str:
        if self.llm_client:
            evidence_text = "\n".join(
                f"[{item.get('anchor')}] page {item.get('page')}: {item.get('excerpt', '')}" for item in evidence[:8]
            )
            system_prompt = (
                "You are a credit agreement ops analyst. "
                "Use only provided evidence. Cite anchors in square brackets. "
                "If unresolved, say exactly what is unresolved."
            )
            user_prompt = (
                f"Question: {question}\n\n"
                f"Scratchpad findings:\n{scratchpad}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                f"Consistency check: {consistency}\n"
            )
            try:
                answer = self.llm_client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
                if self.model_label:
                    return f"(model: {self.model_label})\n{answer}"
                return answer
            except Exception:
                pass

        return self._fallback(question=question, evidence=evidence, consistency=consistency)


class BuildSummaryReportTool:
    name = "build_summary_report"

    def run(self, instruction: str, extraction: dict[str, Any], qa: list[dict[str, str]]) -> str:
        lines: list[str] = []
        lines.append("# Agent Run Summary")
        lines.append("")
        lines.append("## Instruction")
        lines.append(instruction)
        lines.append("")
        lines.append("## Extracted Signals")
        for key, values in extraction.get("signals", {}).items():
            lines.append(f"- **{key}**: {', '.join(values) if values else 'None detected'}")
        if extraction.get("field_extraction"):
            lines.append("")
            lines.append("## Schema Extraction")
            lines.append(f"- **document_type**: {extraction.get('document_type', 'unknown')}")
            lines.append(f"- **schema_version**: {extraction.get('schema_version', 'unknown')}")
            consistency = extraction.get("consistency", {})
            lines.append(f"- **consistency**: {consistency.get('status')} ({consistency.get('score')})")
            for field_name, row in extraction.get("field_extraction", {}).items():
                value = row.get("value") or "Not found"
                lines.append(f"- **{field_name}**: {value}")
        lines.append("")
        lines.append("## Q&A")
        if qa:
            for item in qa:
                lines.append(f"### Q: {item['question']}")
                lines.append(item["answer"])
                lines.append("")
        else:
            lines.append("- No questions provided")

        return "\n".join(lines)
