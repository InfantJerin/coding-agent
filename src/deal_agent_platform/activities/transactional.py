from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TransactionalActivities:
    """Scaffold for transactional read/write activities."""

    compliance_status: dict[str, str] = field(default_factory=dict)
    discrepancies: list[dict[str, Any]] = field(default_factory=list)
    computation_results: list[dict[str, Any]] = field(default_factory=list)

    def get_compliance_status(self, context_id: str) -> str | None:
        return self.compliance_status.get(context_id)

    def update_compliance_status(
        self,
        *,
        context_id: str,
        status: str,
        evidence: str,
        as_of: str,
    ) -> None:
        self.compliance_status[context_id] = status
        self.discrepancies.append(
            {
                "type": "status_update",
                "context_id": context_id,
                "status": status,
                "evidence": evidence,
                "as_of": as_of,
            }
        )

    def record_discrepancy(
        self,
        *,
        context_id: str,
        field: str,
        expected: Any,
        actual: Any,
        severity: str,
    ) -> None:
        self.discrepancies.append(
            {
                "type": "field_discrepancy",
                "context_id": context_id,
                "field": field,
                "expected": expected,
                "actual": actual,
                "severity": severity,
            }
        )

    def record_computation_result(
        self,
        *,
        context_id: str,
        calc_type: str,
        result: dict[str, Any],
        inputs: dict[str, Any],
    ) -> None:
        self.computation_results.append(
            {
                "context_id": context_id,
                "calc_type": calc_type,
                "result": result,
                "inputs": inputs,
            }
        )
