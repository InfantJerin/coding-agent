import unittest

from tools.document_tools import BuildDocMapTool, LoadDocumentsTool
from tools.retrieval_tools import BuildChunkIndexTool, ChunkDocMapSectionsTool, ChunkDocumentTool, RetrieveChunksTool


class RetrievalToolsTests(unittest.TestCase):
    def test_retrieval_returns_relevant_chunk(self) -> None:
        text = (
            "Facility amount is $250 million. "
            "Maturity date is March 31, 2031. "
            "Leverage ratio covenant is 4.5x."
        )
        chunks = ChunkDocumentTool().run(text=text, chunk_size=80, overlap=0)
        index = BuildChunkIndexTool().run(chunks=chunks)
        hits = RetrieveChunksTool().run(query="What is the maturity date?", index=index, top_k=2)

        self.assertTrue(hits)
        merged = " ".join(hit["text"].lower() for hit in hits)
        self.assertIn("maturity", merged)

    def test_section_aware_chunking_from_doc_map(self) -> None:
        store = LoadDocumentsTool().run(["examples/sample_credit_agreement.txt"])
        doc_map = BuildDocMapTool().run(store)
        chunks = ChunkDocMapSectionsTool().run(doc_map=doc_map, max_chars=500)
        self.assertTrue(chunks)
        index = BuildChunkIndexTool().run(chunks=chunks)
        hits = RetrieveChunksTool().run(query="Applicable Margin means", index=index, top_k=3)
        self.assertTrue(hits)
        self.assertTrue(any("section_no" in item for item in hits))


if __name__ == "__main__":
    unittest.main()
