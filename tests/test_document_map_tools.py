import unittest

from tools.document_tools import BuildDocMapTool, FollowReferenceTool, LoadDocumentsTool, ReadDefinitionTool, SearchInDocTool


class DocumentMapToolsTests(unittest.TestCase):
    def test_build_map_has_sections_and_defs(self) -> None:
        store = LoadDocumentsTool().run(["examples/sample_credit_agreement.txt"])
        doc_map = BuildDocMapTool().run(store)

        self.assertGreaterEqual(len(doc_map["sections"]), 3)
        self.assertGreaterEqual(len(doc_map["definitions"]), 2)
        self.assertGreaterEqual(len(doc_map["xrefs"]), 1)

    def test_read_definition_and_follow_ref(self) -> None:
        store = LoadDocumentsTool().run(["examples/sample_credit_agreement.txt"])
        doc_map = BuildDocMapTool().run(store)
        doc_id = doc_map["document_store"]["documents"][0]["doc_id"]

        definition = ReadDefinitionTool().run(doc_map=doc_map, term="Applicable Margin", doc_id=doc_id)
        self.assertTrue(definition["found"])

        hits = SearchInDocTool().run(doc_map=doc_map, query="Section 6.02", scope="section", top_k=3)
        self.assertTrue(hits)

        target = FollowReferenceTool().run(doc_map=doc_map, target_text="Section 6.02", doc_id=doc_id)
        self.assertTrue(target["resolved"])


if __name__ == "__main__":
    unittest.main()
