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


if __name__ == "__main__":
    unittest.main()
