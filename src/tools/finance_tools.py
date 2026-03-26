from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from agent_core.models import ConsistencyResult, ExtractionEvidence, ExtractionField
from llm.providers import LLMClient
from schemas.finance_registry import list_document_types, resolve_schema


def _safe_parse_json(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except Exception:
        # Try to find a JSON object in the string
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


GRAPH_OPERATOR_TYPES = {
    "LOOKUP",
    "ARITHMETIC",
    "CONDITIONAL",
    "COMPARE",
    "MIN",
    "MAX",
    "FLOOR",
    "CAP",
    "DATE_GATE",
    "BOOLEAN_AND",
    "BOOLEAN_OR",
    "REFERENCE",
    "AGGREGATE",
    "CONSTANT",
    "RATE_CALC",
}


def _to_snake_case(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", cleaned).strip("_")


def _parse_percent_value(raw: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", raw)
    if not match:
        return None
    return float(match.group(1))


def _pct_to_bps(raw: str) -> int | None:
    pct = _parse_percent_value(raw)
    if pct is None:
        return None
    return int(round(pct * 100))


def _parse_money_to_number(raw: str) -> int | None:
    match = re.search(r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion|m|bn)?", raw, re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    scale = (match.group(2) or "").lower()
    if scale in {"million", "m"}:
        amount *= 1_000_000
    elif scale in {"billion", "bn"}:
        amount *= 1_000_000_000
    return int(amount)


def _find_section_for_anchor(doc_map: dict[str, Any], anchor: str) -> dict[str, Any] | None:
    anchor_row = doc_map.get("anchors", {}).get(anchor)
    if not anchor_row:
        return None
    doc_id = anchor_row.get("doc_id")
    page = int(anchor_row.get("page", 0))
    block = int(anchor_row.get("block", 0))
    preceding: list[tuple[int, dict[str, Any]]] = []
    following: list[tuple[int, dict[str, Any]]] = []
    for section in doc_map.get("sections", []):
        if section.get("doc_id") != doc_id:
            continue
        if not (int(section.get("page_start", page)) <= page <= int(section.get("page_end", page))):
            continue
        block_start = int(section.get("block_start", block))
        distance = abs(block - block_start)
        if block_start <= block:
            preceding.append((distance, section))
        else:
            following.append((distance, section))
    if preceding:
        preceding.sort(key=lambda row: (row[0], -int(row[1].get("block_start", 0))))
        return preceding[0][1]
    if not following:
        return None
    following.sort(key=lambda row: (row[0], int(row[1].get("block_start", 0))))
    return following[0][1]


def _build_source(doc_map: dict[str, Any], anchor: str, fallback: str) -> str:
    section = _find_section_for_anchor(doc_map, anchor)
    if not section:
        return fallback
    section_no = section.get("section_no") or "unknown"
    title = section.get("title") or "Untitled"
    return f"Section {section_no} — {title}"


def _parse_natural_date(raw: str) -> str | None:
    cleaned = raw.strip().rstrip(".")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _extract_node_refs(value: Any, known_node_ids: set[str]) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        if value in known_node_ids:
            refs.add(value)
        return refs
    if isinstance(value, list):
        for item in value:
            refs.update(_extract_node_refs(item, known_node_ids))
        return refs
    if isinstance(value, dict):
        for item in value.values():
            refs.update(_extract_node_refs(item, known_node_ids))
    return refs


def _normalize_relops(value: str) -> str:
    return (
        value.replace("≥", ">=")
        .replace("≤", "<=")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )


def _roman_to_int(value: str) -> int | None:
    roman = {"I": 1, "V": 5, "X": 10}
    total = 0
    prev = 0
    text = value.upper().strip()
    if not text:
        return None
    for char in reversed(text):
        current = roman.get(char)
        if current is None:
            return None
        if current < prev:
            total -= current
        else:
            total += current
            prev = current
    return total or None


class ExtractCreditAgreementGraphTool:
    name = "extract_credit_agreement_graph"

    def _deal_info(self, text: str) -> dict[str, Any]:
        effective_match = re.search(
            r'(?:"Effective Date"|Closing Date)\s+means\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})',
            text,
        )
        if not effective_match:
            effective_match = re.search(r"dated\s+as\s+of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
        borrower_match = re.search(r"\b([A-Z][A-Za-z0-9&.,' -]+?)\s+(?:as\s+)?Borrower\b", text)
        agent_match = re.search(r"\b([A-Z][A-Za-z0-9&.,' -]+?)\s+as\s+(?:the\s+)?(?:Administrative\s+)?Agent\b", text)
        maturity_match = re.search(
            r'"Maturity Date"\s+means\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})',
            text,
        )
        total_commitment = _parse_money_to_number(text) or 0
        amendment_history: list[dict[str, str]] = []
        for match in re.finditer(
            r"(Amendment No\.\s*\d+).*?(?:dated|effective)\s+(?:as of\s+)?([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
            text,
            re.IGNORECASE | re.DOTALL,
        ):
            amendment_history.append(
                {
                    "amendment": match.group(1).strip(),
                    "date": _parse_natural_date(match.group(2)) or match.group(2).strip(),
                    "summary": "Parsed from amendment reference in provided text.",
                }
            )
        return {
            "borrower": borrower_match.group(1).strip() if borrower_match else "Borrower",
            "facility_type": "revolving_credit" if "revolving" in text.lower() else "unknown",
            "total_commitment": total_commitment,
            "effective_date": _parse_natural_date(effective_match.group(1)) if effective_match else None,
            "maturity_date": _parse_natural_date(maturity_match.group(1)) if maturity_match else None,
            "agent": agent_match.group(1).strip() if agent_match else None,
            "amendment_history": amendment_history,
        }

    def _upsert_node(self, nodes: list[dict[str, Any]], node: dict[str, Any]) -> None:
        for idx, existing in enumerate(nodes):
            if existing["id"] == node["id"]:
                nodes[idx] = node
                return
        nodes.append(node)

    def _find_node(self, nodes: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
        return next((node for node in nodes if node["id"] == node_id), None)

    def _append_input_spec(
        self,
        input_specs: list[dict[str, Any]],
        *,
        param_id: str,
        label: str,
        source_type: str,
        frequency: str,
        unit: str,
        description: str,
        defined_in: str,
        staleness_threshold_days: int | None,
    ) -> None:
        if any(row["param_id"] == param_id for row in input_specs):
            return
        input_specs.append(
            {
                "param_id": param_id,
                "label": label,
                "source_type": source_type,
                "frequency": frequency,
                "staleness_threshold_days": staleness_threshold_days,
                "unit": unit,
                "description": description,
                "defined_in": defined_in,
            }
        )

    def _anchors_in_order(self, doc_map: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        rows = list(doc_map.get("anchors", {}).items())
        rows.sort(key=lambda item: (int(item[1].get("page", 0)), int(item[1].get("block", 0))))
        return rows

    def _append_metric_input(
        self,
        input_specs: list[dict[str, Any]],
        *,
        param_id: str,
        source: str,
        label: str,
        unit: str,
        description: str,
        frequency: str = "Event-driven",
        source_type: str = "Credit Agreement",
        staleness_threshold_days: int | None = None,
    ) -> None:
        self._append_input_spec(
            input_specs,
            param_id=param_id,
            label=label,
            source_type=source_type,
            frequency=frequency,
            unit=unit,
            description=description,
            defined_in=source,
            staleness_threshold_days=staleness_threshold_days,
        )

    def _condition_from_ratio_text(self, raw: str) -> str | None:
        text = _normalize_relops(raw.lower())
        patterns = [
            (r"greater than or equal to\s+(\d+(?:\.\d+)?)", ">="),
            (r"at least\s+(\d+(?:\.\d+)?)", ">="),
            (r">=\s*(\d+(?:\.\d+)?)", ">="),
            (r"greater than\s+(\d+(?:\.\d+)?)", ">"),
            (r">\s*(\d+(?:\.\d+)?)", ">"),
            (r"less than or equal to\s+(\d+(?:\.\d+)?)", "<="),
            (r"<=\s*(\d+(?:\.\d+)?)", "<="),
            (r"less than\s+(\d+(?:\.\d+)?)", "<"),
            (r"<\s*(\d+(?:\.\d+)?)", "<"),
        ]
        for pattern, operator in patterns:
            match = re.search(pattern, text)
            if match:
                return f"{operator} {match.group(1)}"
        return None

    def _metric_node_id(self, header: str) -> str | None:
        normalized = _to_snake_case(header)
        mapping = {
            "applicable_margin": "applicable_margin_bps",
            "term_benchmark_spread": "term_benchmark_spread_bps",
            "rfr_spread": "rfr_spread_bps",
            "abr_spread": "abr_spread_bps",
            "base_rate_spread": "base_rate_spread_bps",
            "commitment_fee": "commitment_fee_bps",
            "commitment_fee_rate": "commitment_fee_bps",
            "letter_of_credit_fee": "letter_of_credit_fee_bps",
        }
        for key, value in mapping.items():
            if key in normalized:
                return value
        if "margin" in normalized:
            return f"{normalized}_bps"
        if "spread" in normalized:
            return f"{normalized}_bps"
        if "fee" in normalized:
            return f"{normalized}_bps"
        return None

    def _parse_grid_tables(
        self,
        text: str,
        doc_map: dict[str, Any],
        nodes: list[dict[str, Any]],
        input_specs: list[dict[str, Any]],
        assumptions: list[str],
    ) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            if "|" not in line:
                continue
            header_cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            if len(header_cells) < 2:
                continue
            if "leverage ratio" not in header_cells[0].lower():
                continue
            metric_columns: list[tuple[int, str, str]] = []
            for col_idx, header in enumerate(header_cells[1:], start=1):
                node_id = self._metric_node_id(header)
                if node_id:
                    metric_columns.append((col_idx, header, node_id))
            if not metric_columns:
                continue

            rows: list[dict[str, Any]] = []
            cursor = idx + 1
            while cursor < len(lines) and "|" in lines[cursor]:
                cells = [cell.strip() for cell in lines[cursor].split("|") if cell.strip()]
                if len(cells) >= len(header_cells):
                    rows.append({"ratio": cells[0], "values": cells[1:]})
                cursor += 1
            if not rows:
                continue

            source_line = line
            anchor = next(
                (
                    anchor_name
                    for anchor_name, row in self._anchors_in_order(doc_map)
                    if source_line in str(row.get("text", "")) or str(row.get("text", "")) in source_line
                ),
                "",
            )
            source = _build_source(doc_map=doc_map, anchor=anchor, fallback=source_line)
            self._append_metric_input(
                input_specs,
                param_id="total_leverage_ratio",
                source=source,
                label="Total Leverage Ratio",
                source_type="Compliance Certificate",
                frequency="Quarterly",
                unit="ratio",
                description="Most recently tested leverage ratio used to select the pricing level.",
                staleness_threshold_days=90,
            )

            for col_idx, header, node_id in metric_columns:
                table: list[dict[str, Any]] = []
                for row in rows:
                    if len(row["values"]) < col_idx:
                        continue
                    condition = self._condition_from_ratio_text(row["ratio"])
                    value_bps = _pct_to_bps(row["values"][col_idx - 1])
                    if not condition or value_bps is None:
                        continue
                    label_match = re.search(r"(category|level)\s+([ivx]+|\d+)", row["ratio"], re.IGNORECASE)
                    label = label_match.group(0) if label_match else row["ratio"]
                    table.append({"condition": condition, "value": value_bps, "label": label})
                if not table:
                    continue
                self._upsert_node(
                    nodes,
                    {
                        "id": node_id,
                        "type": "LOOKUP",
                        "config": {"input": "total_leverage_ratio", "table": table},
                        "source": source,
                        "output_unit": "bps",
                        "notes": f'Parsed pricing grid for "{header}".',
                    },
                )

            initial_line = next(
                (
                    candidate
                    for candidate in lines[idx: min(len(lines), cursor + 5)]
                    if "until the first adjustment date" in candidate.lower() and "level" in candidate.lower()
                ),
                None,
            )
            if initial_line:
                level_match = re.search(r"level\s+([ivx]+|\d+)", initial_line, re.IGNORECASE)
                margin_node = self._find_node(nodes, "applicable_margin_bps")
                if level_match and margin_node and margin_node["type"] == "LOOKUP":
                    level = level_match.group(0).lower()
                    initial_row = next(
                        (row for row in margin_node["config"]["table"] if str(row.get("label", "")).lower() == level),
                        None,
                    )
                    if not initial_row:
                        level_index = _roman_to_int(level_match.group(1)) if not level_match.group(1).isdigit() else int(level_match.group(1))
                        if level_index and 1 <= level_index <= len(margin_node["config"]["table"]):
                            initial_row = margin_node["config"]["table"][level_index - 1]
                    if initial_row:
                        self._upsert_node(
                            nodes,
                            {
                                "id": "initial_applicable_margin_bps",
                                "type": "CONSTANT",
                                "config": {"value": initial_row["value"]},
                                "source": source,
                                "output_unit": "bps",
                                "notes": "Initial pricing level parsed from the temporary period clause.",
                            },
                        )
                        self._append_metric_input(
                            input_specs,
                            param_id="first_adjustment_date",
                            source=source,
                            label="First Adjustment Date",
                            unit="date",
                            description="Date when initial pricing ceases and the leverage-ratio grid controls.",
                        )
                        self._upsert_node(
                            nodes,
                            {
                                "id": "applicable_margin_bps_initial_period",
                                "type": "DATE_GATE",
                                "config": {
                                    "input": "initial_applicable_margin_bps",
                                    "active_from": self._deal_info(text).get("effective_date") or "closing_date",
                                    "active_until": "first_adjustment_date",
                                    "when_inactive": "applicable_margin_bps",
                                },
                                "source": source,
                                "output_unit": "bps",
                                "notes": "Initial pricing applies until the first adjustment date.",
                            },
                        )
                    else:
                        assumptions.append(f"Could not map {level_match.group(0)} to a row in the Applicable Margin grid.")

    def _extract_definition_nodes(
        self,
        doc_map: dict[str, Any],
        nodes: list[dict[str, Any]],
    ) -> None:
        for definition in doc_map.get("definitions", []):
            term = str(definition.get("term", ""))
            definition_text = str(definition.get("text", ""))
            term_snake = _to_snake_case(term)
            source = _build_source(
                doc_map=doc_map,
                anchor=str(definition.get("anchor", "")),
                fallback=f'Definition "{term}"',
            )

            if any(token in term.lower() for token in ("margin", "spread", "fee")):
                bps = _pct_to_bps(definition_text)
                if bps is None:
                    continue
                node_id = self._metric_node_id(term) or f"{term_snake}_bps"
                self._upsert_node(
                    nodes,
                    {
                        "id": node_id,
                        "type": "CONSTANT",
                        "config": {"value": bps},
                        "source": source,
                        "output_unit": "bps",
                        "notes": f'Parsed from definition text for "{term}".',
                    },
                )
                continue

            if "rate" in term.lower():
                pct = _parse_percent_value(definition_text)
                if pct is None:
                    continue
                self._upsert_node(
                    nodes,
                    {
                        "id": f"{term_snake}_pct",
                        "type": "CONSTANT",
                        "config": {"value": round(pct / 100, 6)},
                        "source": source,
                        "output_unit": "pct",
                        "notes": f'Parsed from definition text for "{term}".',
                    },
                )

    def _extract_base_rate_nodes(
        self,
        doc_map: dict[str, Any],
        nodes: list[dict[str, Any]],
        input_specs: list[dict[str, Any]],
    ) -> str | None:
        base_rate_node_or_param: str | None = None
        for anchor, row in self._anchors_in_order(doc_map):
            line = str(row.get("text", ""))
            lower = _normalize_relops(line.lower())
            source = _build_source(doc_map=doc_map, anchor=anchor, fallback=line[:80])

            if "term sofr" in lower:
                base_rate_node_or_param = "term_sofr_rate"
                self._append_metric_input(
                    input_specs,
                    param_id="term_sofr_rate",
                    source=source,
                    label="Term SOFR Rate",
                    source_type="Bloomberg",
                    frequency="Daily",
                    unit="pct",
                    description="Observed benchmark base rate used for floating-rate loans.",
                    staleness_threshold_days=1,
                )
                floor_match = re.search(r"term sofr.*?(?:not be less than|floor of)\s+(\d+(?:\.\d+)?)\s*%", lower)
                if floor_match:
                    self._upsert_node(
                        nodes,
                        {
                            "id": "term_sofr_rate_floor",
                            "type": "FLOOR",
                            "config": {"input": "term_sofr_rate", "floor_value": round(float(floor_match.group(1)) / 100, 6)},
                            "source": source,
                            "output_unit": "pct",
                            "notes": "Base-rate floor parsed from interest benchmark clause.",
                        },
                    )
                    base_rate_node_or_param = "term_sofr_rate_floor"
                cap_match = re.search(r"term sofr.*?(?:not exceed|cap of)\s+(\d+(?:\.\d+)?)\s*%", lower)
                if cap_match:
                    input_ref = base_rate_node_or_param or "term_sofr_rate"
                    self._upsert_node(
                        nodes,
                        {
                            "id": "term_sofr_rate_cap",
                            "type": "CAP",
                            "config": {"input": input_ref, "cap_value": round(float(cap_match.group(1)) / 100, 6)},
                            "source": source,
                            "output_unit": "pct",
                            "notes": "Base-rate cap parsed from interest benchmark clause.",
                        },
                    )
                    base_rate_node_or_param = "term_sofr_rate_cap"
        return base_rate_node_or_param

    def _extract_overlay_and_reference_nodes(
        self,
        doc_map: dict[str, Any],
        nodes: list[dict[str, Any]],
        input_specs: list[dict[str, Any]],
        assumptions: list[str],
    ) -> str:
        current_margin_ref = "applicable_margin_bps_initial_period" if self._find_node(nodes, "applicable_margin_bps_initial_period") else "applicable_margin_bps"
        if not self._find_node(nodes, current_margin_ref):
            return current_margin_ref

        for anchor, row in self._anchors_in_order(doc_map):
            line = str(row.get("text", ""))
            lower = line.lower()
            source = _build_source(doc_map=doc_map, anchor=anchor, fallback=line[:80])

            if "event of default" in lower and "increased by" in lower and "applicable margin" in lower:
                spread = _pct_to_bps(line)
                if spread is None:
                    continue
                self._append_metric_input(
                    input_specs,
                    param_id="is_event_of_default",
                    source=source,
                    label="Event of Default Active",
                    unit="bool",
                    description="True while an Event of Default is continuing.",
                    frequency="Event-driven",
                    source_type="Loan Admin System",
                )
                self._upsert_node(
                    nodes,
                    {
                        "id": "default_interest_increment_bps",
                        "type": "CONSTANT",
                        "config": {"value": spread},
                        "source": source,
                        "output_unit": "bps",
                        "notes": "Default-rate increment parsed from the event-of-default clause.",
                    },
                )
                self._upsert_node(
                    nodes,
                    {
                        "id": "defaulted_applicable_margin_bps",
                        "type": "ARITHMETIC",
                        "config": {
                            "operands": [current_margin_ref, "default_interest_increment_bps"],
                            "operator": "+",
                        },
                        "source": source,
                        "output_unit": "bps",
                        "notes": "Adds the default increment to the otherwise applicable margin.",
                    },
                )
                self._upsert_node(
                    nodes,
                    {
                        "id": "effective_applicable_margin_bps",
                        "type": "CONDITIONAL",
                        "config": {
                            "condition": "is_event_of_default",
                            "then": "defaulted_applicable_margin_bps",
                            "else": current_margin_ref,
                        },
                        "source": source,
                        "output_unit": "bps",
                        "notes": "Applies default pricing only while an Event of Default is continuing.",
                    },
                )
                current_margin_ref = "effective_applicable_margin_bps"

            ref_match = re.search(
                r"(letter of credit fee|lc fee|fronting fee).*?(?:equal to|same as)\s+the\s+([a-z][a-z\s]+?)(?:\.|,|$)",
                lower,
            )
            if ref_match:
                source_metric = self._metric_node_id(ref_match.group(2)) or _to_snake_case(ref_match.group(2))
                if self._find_node(nodes, source_metric):
                    target_id = self._metric_node_id(ref_match.group(1)) or f"{_to_snake_case(ref_match.group(1))}_bps"
                    self._upsert_node(
                        nodes,
                        {
                            "id": target_id,
                            "type": "REFERENCE",
                            "config": {"ref": source_metric},
                            "source": source,
                            "output_unit": "bps",
                            "notes": f'Reference clause aliases "{ref_match.group(1)}" to "{ref_match.group(2)}".',
                        },
                    )
                else:
                    assumptions.append(f"Skipped reference for '{ref_match.group(1)}' because '{ref_match.group(2)}' was not extracted.")

            fee_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s+(?:per annum\s+)?commitment fee", line, re.IGNORECASE)
            if fee_match and not self._find_node(nodes, "commitment_fee_bps"):
                self._upsert_node(
                    nodes,
                    {
                        "id": "commitment_fee_bps",
                        "type": "CONSTANT",
                        "config": {"value": int(round(float(fee_match.group(1)) * 100))},
                        "source": source,
                        "output_unit": "bps",
                        "notes": "Commitment fee parsed directly from clause text.",
                    },
                )

        return current_margin_ref

    def _extract_rate_formula_nodes(
        self,
        doc_map: dict[str, Any],
        nodes: list[dict[str, Any]],
        margin_ref: str,
        base_rate_ref: str | None,
        assumptions: list[str],
    ) -> None:
        for anchor, row in self._anchors_in_order(doc_map):
            line = str(row.get("text", ""))
            lower = line.lower()
            source = _build_source(doc_map=doc_map, anchor=anchor, fallback=line[:80])
            if "interest rate" not in lower or "plus applicable margin" not in lower:
                continue
            if not self._find_node(nodes, margin_ref):
                assumptions.append("Skipped rate formula because Applicable Margin was not extracted.")
                continue
            if not base_rate_ref:
                assumptions.append("Skipped rate formula because base-rate input was not extracted.")
                continue
            self._upsert_node(
                nodes,
                {
                    "id": "revolving_loan_interest_rate",
                    "type": "RATE_CALC",
                    "config": {"base_rate": base_rate_ref, "input": margin_ref},
                    "source": source,
                    "output_unit": "pct",
                    "notes": "Interest clause combines the floating benchmark with the applicable spread.",
                },
            )

    def run(self, text: str, doc_map: dict[str, Any]) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        input_specs: list[dict[str, Any]] = []
        low_confidence_nodes: list[str] = []
        missing_references: list[str] = []
        assumptions: list[str] = []
        self._extract_definition_nodes(doc_map=doc_map, nodes=nodes)
        self._parse_grid_tables(text=text, doc_map=doc_map, nodes=nodes, input_specs=input_specs, assumptions=assumptions)
        base_rate_ref = self._extract_base_rate_nodes(doc_map=doc_map, nodes=nodes, input_specs=input_specs)
        margin_ref = self._extract_overlay_and_reference_nodes(
            doc_map=doc_map,
            nodes=nodes,
            input_specs=input_specs,
            assumptions=assumptions,
        )
        self._extract_rate_formula_nodes(
            doc_map=doc_map,
            nodes=nodes,
            margin_ref=margin_ref,
            base_rate_ref=base_rate_ref,
            assumptions=assumptions,
        )

        xref_targets = {str(ref.get("target_text", "")).strip() for ref in doc_map.get("xrefs", [])}
        for target in sorted(t for t in xref_targets if t):
            resolved = any(str(ref.get("target_text", "")).strip() == target and ref.get("resolved_anchor") for ref in doc_map.get("xrefs", []))
            if not resolved:
                missing_references.append(target)

        valid_nodes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for node in nodes:
            if node["type"] not in GRAPH_OPERATOR_TYPES:
                low_confidence_nodes.append(node["id"])
                continue
            if node["id"] in seen_ids:
                continue
            seen_ids.add(node["id"])
            valid_nodes.append(node)

        node_ids = {node["id"] for node in valid_nodes}
        edges: list[dict[str, str]] = []
        seen_edges: set[tuple[str, str]] = set()
        for node in valid_nodes:
            for ref in sorted(_extract_node_refs(node.get("config", {}), node_ids)):
                key = (ref, node["id"])
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append({"from": ref, "to": node["id"]})

        return {
            "deal_info": self._deal_info(text),
            "nodes": valid_nodes,
            "input_specs": input_specs,
            "edges": edges,
            "extraction_metadata": {
                "total_nodes": len(valid_nodes),
                "total_inputs": len(input_specs),
                "low_confidence_nodes": low_confidence_nodes,
                "missing_references": missing_references,
                "assumptions": assumptions,
            },
        }


class ExtractFinanceSignalsTool:
    name = "extract_finance_signals"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self.graph_tool = ExtractCreditAgreementGraphTool()

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

    def _resolve_doc_type(self, instruction: str, text: str, document_type: str | None, schema_path: str | None = None) -> str:
        if schema_path and document_type:
            return document_type
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

    def _llm_extract_field(
        self,
        field_name: str,
        field_description: str,
        candidate_blocks: list[dict[str, Any]],
    ) -> tuple[str | None, str | None]:
        """Use LLM to extract a field value from candidate blocks.
        Returns (value, quoted_text) or (None, None) on failure."""
        if not self.llm_client or not candidate_blocks:
            return None, None
        context = "\n\n".join(b["text"] for b in candidate_blocks[:6])
        prompt = (
            f'Extract the value of "{field_name}" from the following text.\n'
            f"Field description: {field_description}\n"
            f'Return JSON: {{"value": "<extracted value or null>", "quoted_text": "<exact quote>"}}\n\n'
            f"Text:\n{context}"
        )
        try:
            raw = self.llm_client.generate(
                system_prompt="You are a financial term extractor. Return only valid JSON.",
                user_prompt=prompt,
            )
            parsed = _safe_parse_json(raw)
            if parsed and parsed.get("value") and parsed["value"] != "null":
                return str(parsed["value"]), parsed.get("quoted_text")
        except Exception:
            pass
        return None, None

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
        schema_path: str | None = None,
    ) -> dict[str, Any]:
        extraction: dict[str, Any] = {
            "instruction": instruction,
            "signals": {},
        }
        for key, pattern in self._patterns.items():
            matches = pattern.findall(text)
            extraction["signals"][key] = sorted(set(m.strip() for m in matches if m.strip()))[:25]

        doc_type = self._resolve_doc_type(instruction=instruction, text=text, document_type=document_type, schema_path=schema_path)
        resolved_doc_type, schema = resolve_schema(document_type=doc_type, schema_path=schema_path)
        extraction["document_type"] = resolved_doc_type
        extraction["schema_version"] = schema["version"]
        if resolved_doc_type == "credit_agreement" and doc_map:
            extraction["graph_extraction"] = self.graph_tool.run(text=text, doc_map=doc_map)

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
            if not value and ranked_blocks:
                llm_value, _ = self._llm_extract_field(
                    field_name=name,
                    field_description=field.get("description", " ".join(field["term_hints"])),
                    candidate_blocks=ranked_blocks,
                )
                value = llm_value
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
        warnings: list[str] = []
        required = [field["name"] for field in schema["fields"] if field.get("required")]
        for key in required:
            row = field_rows.get(key)
            if not row or not row.found:
                issues.append(f"Missing required field: {key}")

        for rule in schema.get("validations", []) if isinstance(schema.get("validations", []), list) else []:
            if not isinstance(rule, dict):
                continue
            rule_type = str(rule.get("rule", "")).strip().lower()
            if rule_type == "contains":
                field_name = str(rule.get("field", "")).strip()
                expected = str(rule.get("value", ""))
                when_found = bool(rule.get("when_found", True))
                row = field_rows.get(field_name)
                if not row:
                    continue
                if when_found and row.found and expected and expected not in str(row.value or ""):
                    issues.append(f"{field_name} must contain '{expected}'")
            elif rule_type == "date_order":
                earlier = str(rule.get("earlier", "")).strip()
                later = str(rule.get("later", "")).strip()
                d1 = self._parse_date(field_rows.get(earlier).value if field_rows.get(earlier) else None)
                d2 = self._parse_date(field_rows.get(later).value if field_rows.get(later) else None)
                if d1 and d2 and d1 > d2:
                    issues.append(f"Date order invalid: {earlier} occurs after {later}")
            else:
                warnings.append(f"Unknown validation rule ignored: {rule_type}")

        found_count = sum(1 for row in field_rows.values() if row.found)
        coverage = found_count / max(1, len(field_rows))
        if issues:
            status = "warning"
            score = max(0.0, round(coverage - 0.2, 4))
        else:
            status = "passed"
            score = round(coverage, 4)
        consistency = ConsistencyResult(status=status, score=score, issues=issues, warnings=warnings)
        extraction["consistency"] = {
            "status": consistency.status,
            "score": consistency.score,
            "issues": consistency.issues,
            "warnings": consistency.warnings,
        }
        self._validate_contract(extraction=extraction, schema=schema, field_rows=field_rows, consistency=consistency)

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
        graph = extraction.get("graph_extraction")
        if isinstance(graph, dict) and graph.get("nodes"):
            lines.append("")
            lines.append("## Graph Extraction")
            lines.append(f"- **nodes**: {graph.get('extraction_metadata', {}).get('total_nodes', 0)}")
            lines.append(f"- **inputs**: {graph.get('extraction_metadata', {}).get('total_inputs', 0)}")
            for node in graph.get("nodes", [])[:8]:
                lines.append(f"- **{node.get('id')}** ({node.get('type')}): {node.get('source')}")
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
