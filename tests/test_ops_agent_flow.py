import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
