from __future__ import annotations

from typing import Any

from agent_core.session import DealStore


class CreateDealTool:
    name = "create_deal"

    def __init__(self, deal_store: DealStore) -> None:
        self.deal_store = deal_store

    def run(self, name: str) -> dict[str, Any]:
        meta = self.deal_store.create(name)
        return {"deal_id": meta.deal_id, "name": meta.name, "created_at": meta.created_at}


class AddDocumentToDealTool:
    name = "add_document_to_deal"

    def __init__(self, deal_store: DealStore) -> None:
        self.deal_store = deal_store

    def run(self, deal_id: str, path: str, doc_type: str = "auto", role: str = "primary") -> dict[str, Any]:
        meta = self.deal_store.add_document(deal_id=deal_id, path=path, doc_type=doc_type, role=role)
        return {
            "deal_id": meta.deal_id,
            "name": meta.name,
            "document_count": len(meta.documents),
            "documents": [{"path": d.path, "doc_type": d.doc_type, "role": d.role} for d in meta.documents],
        }


class GetDealSummaryTool:
    name = "get_deal_summary"

    def __init__(self, deal_store: DealStore) -> None:
        self.deal_store = deal_store

    def run(self, deal_id: str) -> dict[str, Any]:
        meta = self.deal_store.load(deal_id)
        if meta is None:
            return {"error": f"Deal not found: {deal_id}"}
        doc_map_cached = self.deal_store.load_doc_map(deal_id) is not None
        return {
            "deal_id": meta.deal_id,
            "name": meta.name,
            "documents": [{"path": d.path, "doc_type": d.doc_type, "role": d.role} for d in meta.documents],
            "doc_map_cached": doc_map_cached,
        }


class ListDealsTool:
    name = "list_deals"

    def __init__(self, deal_store: DealStore) -> None:
        self.deal_store = deal_store

    def run(self) -> list[dict[str, Any]]:
        return [
            {"deal_id": m.deal_id, "name": m.name, "doc_count": len(m.documents)}
            for m in self.deal_store.list_deals()
        ]
