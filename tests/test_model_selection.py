import unittest

from llm.catalog import load_model_catalog
from llm.selection import parse_model_ref, resolve_model_ref


class ModelSelectionTests(unittest.TestCase):
    def test_parse_alias(self) -> None:
        ref = parse_model_ref("sonnet")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.provider, "anthropic")

    def test_resolve_default(self) -> None:
        catalog = load_model_catalog()
        ref = resolve_model_ref(catalog, None)
        self.assertIsNotNone(ref)


if __name__ == "__main__":
    unittest.main()
