import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_core.session import DealDocument, DealMeta, DealStore, Session, SessionStore


class DealStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.store = DealStore(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_and_load(self) -> None:
        meta = self.store.create("test deal")
        self.assertEqual(meta.name, "test deal")
        self.assertTrue(meta.deal_id)

        loaded = self.store.load(meta.deal_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "test deal")
        self.assertEqual(loaded.deal_id, meta.deal_id)

    def test_load_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self.store.load("no-such-id"))

    def test_save_and_reload(self) -> None:
        meta = self.store.create("my deal")
        meta.name = "updated deal"
        self.store.save(meta)

        loaded = self.store.load(meta.deal_id)
        self.assertEqual(loaded.name, "updated deal")

    def test_list_deals(self) -> None:
        self.store.create("deal A")
        self.store.create("deal B")
        deals = self.store.list_deals()
        names = {d.name for d in deals}
        self.assertIn("deal A", names)
        self.assertIn("deal B", names)

    def test_add_document(self) -> None:
        meta = self.store.create("deal with doc")
        updated = self.store.add_document(
            deal_id=meta.deal_id,
            path="/tmp/doc.pdf",
            doc_type="credit_agreement",
            role="primary",
        )
        self.assertEqual(len(updated.documents), 1)
        self.assertEqual(updated.documents[0].path, "/tmp/doc.pdf")
        self.assertEqual(updated.documents[0].role, "primary")

        # Persisted
        reloaded = self.store.load(meta.deal_id)
        self.assertEqual(len(reloaded.documents), 1)

    def test_add_document_unknown_deal_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.store.add_document("no-such", "/tmp/f.pdf", "auto", "primary")

    def test_save_and_load_doc_map(self) -> None:
        meta = self.store.create("doc map deal")
        doc_map = {"anchors": {"a1": {"text": "hello"}}, "sections": []}
        self.store.save_doc_map(meta.deal_id, doc_map)

        loaded = self.store.load_doc_map(meta.deal_id)
        self.assertIsNotNone(loaded)
        self.assertIn("a1", loaded["anchors"])

    def test_load_doc_map_missing_returns_none(self) -> None:
        meta = self.store.create("no map deal")
        self.assertIsNone(self.store.load_doc_map(meta.deal_id))


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.store = SessionStore(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_and_load(self) -> None:
        session = self.store.create(deal_id="deal-1")
        self.assertEqual(session.deal_id, "deal-1")
        self.assertTrue(session.session_id)

        loaded = self.store.load(session.session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.deal_id, "deal-1")

    def test_load_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self.store.load("missing"))

    def test_save_appends_messages(self) -> None:
        session = self.store.create()
        session.messages.append({"role": "user", "content": "hello"})
        self.store.save(session)

        loaded = self.store.load(session.session_id)
        self.assertEqual(len(loaded.messages), 1)
        self.assertEqual(loaded.messages[0]["content"], "hello")

    def test_list_sessions(self) -> None:
        s1 = self.store.create()
        s2 = self.store.create(deal_id="d1")
        sessions = self.store.list_sessions()
        ids = {s["session_id"] for s in sessions}
        self.assertIn(s1.session_id, ids)
        self.assertIn(s2.session_id, ids)

    def test_create_without_deal(self) -> None:
        session = self.store.create()
        self.assertIsNone(session.deal_id)
        loaded = self.store.load(session.session_id)
        self.assertIsNone(loaded.deal_id)
