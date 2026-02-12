import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_core.runner import GenericHeadlessAgent
from profiles.finance_docs import build_finance_docs_profile


class OpsAgentFlowTests(unittest.TestCase):
    def test_respond_includes_reading_trail(self) -> None:
        profile = build_finance_docs_profile()
        runner = GenericHeadlessAgent(profile.registry, profile.policy)
        response, trace = runner.respond(
            instruction="Answer with cited evidence",
            documents=[Path("examples/sample_credit_agreement.txt")],
            query="What is the maturity date?",
        )

        self.assertIn("## Reading Trail", response)
        self.assertTrue(any(item.get("tool") == "build_doc_map" for item in trace))
        self.assertIn("## Session", response)

    def test_respond_supports_task_policy_override(self) -> None:
        profile = build_finance_docs_profile()
        runner = GenericHeadlessAgent(profile.registry, profile.policy)
        _, trace = runner.respond(
            instruction="Answer with cited evidence",
            documents=[Path("examples/sample_credit_agreement.txt")],
            query="What is the facility amount?",
            metadata={"tool_policy_override": {"deny": ["safe_bash"]}},
        )
        self.assertTrue(any(item.get("event") == "respond_started" for item in trace))

    def test_strategy_sets_generic_parse_for_compliance(self) -> None:
        profile = build_finance_docs_profile()
        runner = GenericHeadlessAgent(profile.registry, profile.policy)
        with TemporaryDirectory() as tmp:
            doc = Path(tmp) / "compliance.txt"
            doc.write_text("Compliance Certificate\nFor the period ended March 31, 2026\nBorrower is in compliance.")
            _, trace = runner.respond(
                instruction="Extract compliance terms",
                documents=[doc],
                query="What is compliance status?",
                metadata={"document_type": "compliance_certificate"},
            )
            build_map_calls = [row for row in trace if row.get("tool") == "build_doc_map"]
            self.assertTrue(build_map_calls)
            args = build_map_calls[0].get("args", {})
            self.assertEqual(args.get("parse_strategy"), "generic")


if __name__ == "__main__":
    unittest.main()
