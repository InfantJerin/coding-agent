import os
import unittest

from profiles.finance_docs import resolve_requested_model_from_env


class ProviderPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = {
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
            "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
            "AGENT_MODEL": os.getenv("AGENT_MODEL"),
        }

    def tearDown(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_openai_priority_over_anthropic(self) -> None:
        os.environ["OPENAI_API_KEY"] = "x"
        os.environ["ANTHROPIC_API_KEY"] = "y"
        os.environ.pop("AGENT_MODEL", None)
        self.assertEqual(resolve_requested_model_from_env(), "openai/gpt-4.1-mini")

    def test_fallback_to_anthropic(self) -> None:
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["ANTHROPIC_API_KEY"] = "y"
        os.environ.pop("AGENT_MODEL", None)
        self.assertEqual(resolve_requested_model_from_env(), "anthropic/claude-3-5-sonnet-latest")

    def test_explicit_model_override(self) -> None:
        os.environ["OPENAI_API_KEY"] = "x"
        os.environ["ANTHROPIC_API_KEY"] = "y"
        os.environ["AGENT_MODEL"] = "anthropic/claude-3-5-sonnet-latest"
        self.assertEqual(resolve_requested_model_from_env(), "anthropic/claude-3-5-sonnet-latest")


if __name__ == "__main__":
    unittest.main()
