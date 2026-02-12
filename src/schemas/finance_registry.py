from __future__ import annotations

from typing import Any


SCHEMAS: dict[str, dict[str, Any]] = {
    "credit_agreement": {
        "version": "v1",
        "fields": [
            {
                "name": "facility_amount",
                "required": True,
                "section_hints": ["commitments", "the commitments", "facility", "loans", "amount"],
                "term_hints": ["facility", "commitment", "loan", "amount"],
                "pattern": r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|m)?",
            },
            {
                "name": "maturity_date",
                "required": True,
                "section_hints": ["maturity", "termination", "term", "repayment"],
                "term_hints": ["maturity", "termination", "repayment"],
                "pattern": r"(?:maturity date is|maturity date|terminates? on|termination date is)\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
            },
            {
                "name": "interest_benchmark",
                "required": False,
                "section_hints": ["interest", "benchmark", "rate", "applicable margin", "pricing"],
                "term_hints": ["sofr", "libor", "base rate", "prime rate", "interest rate"],
                "pattern": r"(SOFR|LIBOR|Base Rate|Prime Rate)",
            },
            {
                "name": "conditions_precedent",
                "required": False,
                "section_hints": ["conditions precedent", "conditions to borrowing", "borrowing", "advances"],
                "term_hints": ["condition precedent", "conditions", "borrowing", "request", "notice"],
            },
            {
                "name": "excess_cash_flow_definition",
                "required": False,
                "section_hints": ["definitions", "defined terms"],
                "term_hints": ["excess cash flow", "means"],
            },
        ],
    },
    "compliance_certificate": {
        "version": "v1",
        "fields": [
            {
                "name": "reporting_period_end",
                "required": True,
                "section_hints": ["reporting period", "period end", "fiscal quarter"],
                "term_hints": ["period", "quarter", "ended", "as of"],
                "pattern": r"(?:for the period ended|as of)\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
            },
            {
                "name": "leverage_ratio",
                "required": True,
                "section_hints": ["financial covenant", "leverage ratio", "ratio"],
                "term_hints": ["leverage ratio", "total leverage", "ratio"],
                "pattern": r"(\d+(?:\.\d+)?x)",
            },
            {
                "name": "compliance_status",
                "required": True,
                "section_hints": ["compliance", "certification", "officer certificate"],
                "term_hints": ["in compliance", "not in compliance", "complies", "default"],
                "pattern": r"(in compliance|not in compliance|complies|does not comply)",
            },
        ],
    },
    "rate_notice": {
        "version": "v1",
        "fields": [
            {
                "name": "effective_date",
                "required": True,
                "section_hints": ["rate notice", "effective", "interest period"],
                "term_hints": ["effective", "interest period", "date"],
                "pattern": r"(?:effective|as of)\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
            },
            {
                "name": "benchmark_rate",
                "required": True,
                "section_hints": ["benchmark", "reference rate", "interest"],
                "term_hints": ["sofr", "libor", "base rate", "prime"],
                "pattern": r"(SOFR|LIBOR|Base Rate|Prime Rate)",
            },
            {
                "name": "margin",
                "required": False,
                "section_hints": ["applicable margin", "spread", "pricing"],
                "term_hints": ["margin", "spread", "bps"],
                "pattern": r"(\d+(?:\.\d+)?\s?(?:%|bps))",
            },
        ],
    },
}


def list_document_types() -> list[str]:
    return sorted(SCHEMAS.keys())


def resolve_schema(document_type: str | None) -> tuple[str, dict[str, Any]]:
    if document_type and document_type in SCHEMAS:
        return document_type, SCHEMAS[document_type]
    return "credit_agreement", SCHEMAS["credit_agreement"]

