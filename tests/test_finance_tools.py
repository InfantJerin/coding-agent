import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.document_tools import BuildDocMapTool, LoadDocumentsTool
from tools.finance_tools import ExtractFinanceSignalsTool


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


if __name__ == "__main__":
    unittest.main()
