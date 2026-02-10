from __future__ import annotations

import re
from typing import Any

from llm.providers import LLMClient


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

    def run(self, text: str, instruction: str) -> dict[str, Any]:
        extraction: dict[str, Any] = {
            "instruction": instruction,
            "signals": {},
        }
        for key, pattern in self._patterns.items():
            matches = pattern.findall(text)
            extraction["signals"][key] = sorted(set(m.strip() for m in matches if m.strip()))[:25]
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
