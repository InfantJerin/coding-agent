import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.document_tools import BuildDocMapTool, LoadDocumentsTool
from tools.finance_tools import ExtractCreditAgreementGraphTool, ExtractFinanceSignalsTool


class FinanceToolsTests(unittest.TestCase):
    def test_extract_finance_signals_detects_core_terms(self) -> None:
        text = "Facility is $100 million. Interest is SOFR + margin. Maturity date is 2030."
        tool = ExtractFinanceSignalsTool()
        output = tool.run(text=text, instruction="extract")

        self.assertTrue(output["signals"]["facility_amount"])
        self.assertTrue(any("SOFR" in v.upper() for v in output["signals"]["interest_terms"]))
        self.assertTrue(output["signals"]["maturity"])

    def test_schema_extraction_uses_doc_map(self) -> None:
        store = LoadDocumentsTool().run(["examples/sample_credit_agreement.txt"])
        doc_map = BuildDocMapTool().run(store)
        text = "\n".join(doc_map["document_store"]["documents"][0]["pages"])
        tool = ExtractFinanceSignalsTool()
        output = tool.run(
            text=text,
            instruction="Extract key terms for this credit agreement.",
            doc_map=doc_map,
            document_type="credit_agreement",
        )

        self.assertEqual(output["document_type"], "credit_agreement")
        self.assertIn("field_extraction", output)
        self.assertIn("facility_amount", output["field_extraction"])
        self.assertIn("consistency", output)
        self.assertIn("warnings", output["consistency"])
        self.assertIn("unresolved_dependencies", output["field_extraction"]["facility_amount"])
        self.assertIn("graph_extraction", output)
        graph = output["graph_extraction"]
        self.assertEqual(graph["deal_info"]["total_commitment"], 250000000)
        self.assertTrue(any(node["id"] == "applicable_margin_bps" for node in graph["nodes"]))
        self.assertTrue(any(node["id"] == "revolving_loan_interest_rate" for node in graph["nodes"]))
        self.assertTrue(any(spec["param_id"] == "term_sofr_rate" for spec in graph["input_specs"]))
        self.assertTrue(
            any(
                edge["from"] == "applicable_margin_bps" and edge["to"] == "revolving_loan_interest_rate"
                for edge in graph["edges"]
            )
        )
        self.assertEqual(graph["extraction_metadata"]["total_nodes"], len(graph["nodes"]))

    def test_no_doc_map_returns_skipped_consistency(self) -> None:
        tool = ExtractFinanceSignalsTool()
        output = tool.run(
            text="No structured map is available here.",
            instruction="Extract for compliance certificate",
            doc_map=None,
            document_type="compliance_certificate",
        )
        self.assertEqual(output["consistency"]["status"], "skipped")

    def test_custom_yaml_schema_path(self) -> None:
        with TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "custom_notice.yaml"
            schema_path.write_text(
                "\n".join(
                    [
                        "document_type: custom_notice",
                        "schema:",
                        "  version: v1",
                        "  fields:",
                        "    - name: notice_id",
                        "      required: true",
                        "      section_hints: [\"notice\"]",
                        "      term_hints: [\"notice id\", \"notice\"]",
                        "      pattern: \"Notice ID:\\\\s*([A-Z0-9-]+)\"",
                    ]
                )
            )
            text_path = Path(tmp) / "notice.txt"
            text_path.write_text("Notice\nNotice ID: ABC-123")

            store = LoadDocumentsTool().run([str(text_path)])
            doc_map = BuildDocMapTool().run(document_store=store, parse_strategy="generic")
            text = "\n".join(doc_map["document_store"]["documents"][0]["pages"])

            output = ExtractFinanceSignalsTool().run(
                text=text,
                instruction="Extract custom notice fields.",
                doc_map=doc_map,
                document_type="custom_notice",
                schema_path=str(schema_path),
            )
            self.assertEqual(output["document_type"], "custom_notice")
            self.assertIn("notice_id", output["field_extraction"])
            self.assertTrue(output["field_extraction"]["notice_id"]["found"])

    def test_graph_extraction_handles_lookup_overlays_and_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            text_path = Path(tmp) / "grid_agreement.txt"
            text_path.write_text(
                "\n".join(
                    [
                        "ACME CREDIT AGREEMENT dated as of January 15, 2026.",
                        "Acme Borrower LLC as Borrower.",
                        "Example Bank, N.A. as Administrative Agent.",
                        '"Maturity Date" means January 15, 2031.',
                        "Amendment No. 1 dated February 1, 2026 adjusted pricing.",
                        "Section 2.05 Applicable Rate",
                        "Total Leverage Ratio | Applicable Margin | Commitment Fee Rate",
                        "Greater than or equal to 4.00 | 3.00% | 0.50%",
                        "Less than 4.00 but >= 3.50 | 2.75% | 0.375%",
                        "Less than 3.50 | 2.25% | 0.25%",
                        "The initial Applicable Margin from the Closing Date until the first Adjustment Date shall be the rate corresponding to Level II.",
                        "The interest rate for Revolving Loans shall be Term SOFR plus Applicable Margin.",
                        "Term SOFR shall not be less than 1.00%.",
                        "Upon the occurrence and during the continuance of an Event of Default, the Applicable Margin shall be increased by 2.00% per annum.",
                        "The Letter of Credit Fee shall be equal to the Applicable Margin.",
                    ]
                )
            )

            store = LoadDocumentsTool().run([str(text_path)])
            doc_map = BuildDocMapTool().run(store)
            text = "\n".join(doc_map["document_store"]["documents"][0]["pages"])
            graph = ExtractCreditAgreementGraphTool().run(text=text, doc_map=doc_map)

            nodes = {node["id"]: node for node in graph["nodes"]}
            self.assertEqual(graph["deal_info"]["effective_date"], "2026-01-15")
            self.assertEqual(graph["deal_info"]["maturity_date"], "2031-01-15")
            self.assertEqual(graph["deal_info"]["agent"], "Example Bank, N.A.")
            self.assertEqual(graph["deal_info"]["amendment_history"][0]["date"], "2026-02-01")
            self.assertEqual(nodes["applicable_margin_bps"]["type"], "LOOKUP")
            self.assertEqual(nodes["commitment_fee_bps"]["type"], "LOOKUP")
            self.assertEqual(nodes["term_sofr_rate_floor"]["type"], "FLOOR")
            self.assertEqual(nodes["applicable_margin_bps_initial_period"]["type"], "DATE_GATE")
            self.assertEqual(nodes["effective_applicable_margin_bps"]["type"], "CONDITIONAL")
            self.assertEqual(nodes["letter_of_credit_fee_bps"]["type"], "REFERENCE")
            self.assertEqual(nodes["revolving_loan_interest_rate"]["type"], "RATE_CALC")
            self.assertTrue(any(spec["param_id"] == "total_leverage_ratio" for spec in graph["input_specs"]))
            self.assertTrue(any(spec["param_id"] == "first_adjustment_date" for spec in graph["input_specs"]))
            self.assertTrue(
                any(
                    edge["from"] == "effective_applicable_margin_bps" and edge["to"] == "revolving_loan_interest_rate"
                    for edge in graph["edges"]
                )
            )


if __name__ == "__main__":
    unittest.main()
