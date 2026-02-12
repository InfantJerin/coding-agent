import unittest

from agent_core.tooling import ToolPolicy


class ToolPolicyTests(unittest.TestCase):
    def test_allow_wildcard_and_deny_exact(self) -> None:
        policy = ToolPolicy(allow=["*"], deny=["safe_bash"])

        policy.check("load_documents")
        with self.assertRaises(PermissionError):
            policy.check("safe_bash")

    def test_allow_pattern(self) -> None:
        policy = ToolPolicy(allow=["retrieve_*", "load_documents"], deny=[])
        policy.check("retrieve_chunks")
        policy.check("load_documents")
        with self.assertRaises(PermissionError):
            policy.check("answer_question_from_text")

    def test_merge_task_override_with_deny_precedence(self) -> None:
        base = ToolPolicy(allow=["*"], deny=["safe_bash"])
        merged = base.merged(ToolPolicy(allow=["load_documents", "build_doc_map"], deny=["build_doc_map"]))
        merged.check("load_documents")
        with self.assertRaises(PermissionError):
            merged.check("build_doc_map")
        with self.assertRaises(PermissionError):
            merged.check("safe_bash")


if __name__ == "__main__":
    unittest.main()
