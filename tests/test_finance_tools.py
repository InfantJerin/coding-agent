import unittest

from tools.finance_tools import ExtractFinanceSignalsTool


class FinanceToolsTests(unittest.TestCase):
    def test_extract_finance_signals_detects_core_terms(self) -> None:
        text = "Facility is $100 million. Interest is SOFR + margin. Maturity date is 2030."
        tool = ExtractFinanceSignalsTool()
        output = tool.run(text=text, instruction="extract")

        self.assertTrue(output["signals"]["facility_amount"])
        self.assertTrue(any("SOFR" in v.upper() for v in output["signals"]["interest_terms"]))
        self.assertTrue(output["signals"]["maturity"])


if __name__ == "__main__":
    unittest.main()
