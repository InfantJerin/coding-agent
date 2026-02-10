import unittest

from tools.retrieval_tools import BuildChunkIndexTool, ChunkDocumentTool, RetrieveChunksTool


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


if __name__ == "__main__":
    unittest.main()
