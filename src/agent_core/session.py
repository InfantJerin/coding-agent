from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DealDocument:
    path: str
    doc_type: str
    role: str  # "primary" | "amendment" | "supplement"


@dataclass
class DealMeta:
    deal_id: str
    name: str
    documents: list[DealDocument] = field(default_factory=list)
    created_at: str = field(default_factory=_now)


@dataclass
class Session:
    session_id: str
    deal_id: str | None
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class DealStore:
    def __init__(self, data_dir: Path = Path("./data/deals")) -> None:
        self.data_dir = data_dir

    def _deal_dir(self, deal_id: str) -> Path:
        return self.data_dir / deal_id

    def _meta_path(self, deal_id: str) -> Path:
        return self._deal_dir(deal_id) / "meta.json"

    def create(self, name: str) -> DealMeta:
        deal_id = str(uuid.uuid4())[:8]
        meta = DealMeta(deal_id=deal_id, name=name)
        self._deal_dir(deal_id).mkdir(parents=True, exist_ok=True)
        self.save(meta)
        return meta

    def load(self, deal_id: str) -> DealMeta | None:
        path = self._meta_path(deal_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        docs = [DealDocument(**d) for d in data.get("documents", [])]
        return DealMeta(
            deal_id=data["deal_id"],
            name=data["name"],
            documents=docs,
            created_at=data.get("created_at", ""),
        )

    def save(self, deal_meta: DealMeta) -> None:
        self._deal_dir(deal_meta.deal_id).mkdir(parents=True, exist_ok=True)
        path = self._meta_path(deal_meta.deal_id)
        data = {
            "deal_id": deal_meta.deal_id,
            "name": deal_meta.name,
            "documents": [asdict(d) for d in deal_meta.documents],
            "created_at": deal_meta.created_at,
        }
        path.write_text(json.dumps(data, indent=2))

    def list_deals(self) -> list[DealMeta]:
        if not self.data_dir.exists():
            return []
        result: list[DealMeta] = []
        for d in self.data_dir.iterdir():
            if d.is_dir():
                meta = self.load(d.name)
                if meta:
                    result.append(meta)
        return result

    def add_document(self, deal_id: str, path: str, doc_type: str, role: str) -> DealMeta:
        meta = self.load(deal_id)
        if meta is None:
            raise ValueError(f"Deal not found: {deal_id}")
        meta.documents.append(DealDocument(path=path, doc_type=doc_type, role=role))
        self.save(meta)
        return meta

    def save_doc_map(self, deal_id: str, doc_map: dict[str, Any]) -> None:
        self._deal_dir(deal_id).mkdir(parents=True, exist_ok=True)
        path = self._deal_dir(deal_id) / "doc_map.json"
        path.write_text(json.dumps(doc_map))

    def load_doc_map(self, deal_id: str) -> dict[str, Any] | None:
        path = self._deal_dir(deal_id) / "doc_map.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_chunk_index(self, deal_id: str, chunk_index: dict[str, Any]) -> None:
        self._deal_dir(deal_id).mkdir(parents=True, exist_ok=True)
        (self._deal_dir(deal_id) / "chunk_index.json").write_text(json.dumps(chunk_index))

    def load_chunk_index(self, deal_id: str) -> dict[str, Any] | None:
        path = self._deal_dir(deal_id) / "chunk_index.json"
        return json.loads(path.read_text()) if path.exists() else None


class SessionStore:
    def __init__(self, data_dir: Path = Path("./data/sessions")) -> None:
        self.data_dir = data_dir

    def _session_path(self, session_id: str) -> Path:
        return self.data_dir / f"{session_id}.json"

    def create(self, deal_id: str | None = None) -> Session:
        session_id = str(uuid.uuid4())[:8]
        session = Session(session_id=session_id, deal_id=deal_id)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.save(session)
        return session

    def load(self, session_id: str) -> Session | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return Session(
            session_id=data["session_id"],
            deal_id=data.get("deal_id"),
            messages=data.get("messages", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def save(self, session: Session) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        session.updated_at = _now()
        data = {
            "session_id": session.session_id,
            "deal_id": session.deal_id,
            "messages": session.messages,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
        self._session_path(session.session_id).write_text(json.dumps(data, indent=2))

    def list_sessions(self) -> list[dict[str, Any]]:
        if not self.data_dir.exists():
            return []
        result: list[dict[str, Any]] = []
        for f in self.data_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                result.append({
                    "session_id": data.get("session_id"),
                    "deal_id": data.get("deal_id"),
                    "message_count": len(data.get("messages", [])),
                    "updated_at": data.get("updated_at"),
                })
            except Exception:
                pass
        return result
