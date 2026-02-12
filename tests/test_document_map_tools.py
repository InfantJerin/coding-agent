import unittest

from tools.document_tools import BuildDocMapTool, FollowReferenceTool, LoadDocumentsTool, ReadDefinitionTool, SearchInDocTool


class _FakeLLM:
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        return (
            '[{"section_no":"1.00","title":"Overview","page_start":1,"level":1},'
            '{"section_no":"2.00","title":"Covenants","page_start":2,"level":1}]'
        )


class DocumentMapToolsTests(unittest.TestCase):
    def test_build_map_has_sections_and_defs(self) -> None:
        store = LoadDocumentsTool().run(["examples/sample_credit_agreement.txt"])
        doc_map = BuildDocMapTool().run(store)
        doc_id = doc_map["document_store"]["documents"][0]["doc_id"]

        self.assertGreaterEqual(len(doc_map["sections"]), 3)
        self.assertGreaterEqual(len(doc_map["definitions"]), 2)
        self.assertGreaterEqual(len(doc_map["xrefs"]), 1)
        self.assertIn(doc_id, doc_map["section_tree"])
        self.assertTrue(doc_map["section_tree"][doc_id])
        first = doc_map["section_tree"][doc_id][0]
        self.assertIn("node_id", first)
        self.assertTrue(first["node_id"].startswith("N"))
        self.assertIn("start_index", first)
        self.assertIn("end_index", first)
        self.assertIn("summary", first)
        self.assertIn("key_events", first)

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

    def test_llm_fallback_builds_sections_when_no_toc_or_headings(self) -> None:
        document_store = {
            "documents": [
                {
                    "doc_id": "doc-0",
                    "path": "in-memory.txt",
                    "name": "in-memory.txt",
                    "pages": [
                        "This agreement describes lender obligations and borrower responsibilities.",
                        "The borrower must provide quarterly statements and maintain leverage limits.",
                    ],
                    "total_pages": 2,
                    "outlines": [],
                }
            ]
        }
        doc_map = BuildDocMapTool(llm_client=_FakeLLM()).run(document_store)
        self.assertGreaterEqual(len(doc_map["sections"]), 1)
        self.assertTrue(any(section.get("source") == "llm" for section in doc_map["sections"]))


if __name__ == "__main__":
    unittest.main()
