import unittest

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


if __name__ == "__main__":
    unittest.main()
