from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


_WORD_RE = re.compile(r"[a-zA-Z0-9]{2,}")


def _tokenize(value: str) -> list[str]:
    return [tok.lower() for tok in _WORD_RE.findall(value)]


class ChunkDocumentTool:
    name = "chunk_document"

    def run(self, text: str, chunk_size: int = 900, overlap: int = 120) -> list[dict[str, Any]]:
        cleaned = text.strip()
        if not cleaned:
            return []
        step = max(1, chunk_size - overlap)
        chunks: list[dict[str, Any]] = []
        i = 0
        idx = 0
        while i < len(cleaned):
            chunk_text = cleaned[i : i + chunk_size]
            chunks.append(
                {
                    "chunk_id": f"chunk-{idx}",
                    "start": i,
                    "end": min(i + chunk_size, len(cleaned)),
                    "text": chunk_text,
                }
            )
            i += step
            idx += 1
        return chunks


class ChunkDocMapSectionsTool:
    name = "chunk_doc_map_sections"

    def run(self, doc_map: dict[str, Any], max_chars: int = 1200) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for section in doc_map.get("sections", []):
            doc_id = section.get("doc_id", "")
            section_no = section.get("section_no", "")
            title = section.get("title", "")
            start = int(section.get("page_start", 1))
            end = int(section.get("page_end", start))
            anchors = []
            texts = []
            for anchor, data in doc_map.get("anchors", {}).items():
                if data.get("doc_id") != doc_id:
                    continue
                page = int(data.get("page", 0))
                if start <= page <= end:
                    anchors.append(anchor)
                    texts.append(str(data.get("text", "")))
            joined = " ".join(texts).strip()
            if not joined:
                continue
            chunk_text = joined[:max_chars]
            chunks.append(
                {
                    "chunk_id": f"{doc_id}:{section_no}",
                    "doc_id": doc_id,
                    "section_no": section_no,
                    "title": title,
                    "start_page": start,
                    "end_page": end,
                    "anchors": anchors[:20],
                    "text": chunk_text,
                }
            )

        for definition in doc_map.get("definitions", []):
            chunk_id = f"{definition.get('doc_id')}::def::{definition.get('term')}"
            text = f"{definition.get('term')} means {definition.get('text', '')}".strip()[:max_chars]
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": definition.get("doc_id"),
                    "section_no": "DEFINITIONS",
                    "title": definition.get("term"),
                    "start_page": None,
                    "end_page": None,
                    "anchors": [definition.get("anchor")],
                    "text": text,
                }
            )
        return chunks


class BuildChunkIndexTool:
    name = "build_chunk_index"

    def run(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        df: Counter[str] = Counter()
        tf: dict[str, Counter[str]] = {}
        lengths: dict[str, int] = {}

        for chunk in chunks:
            cid = chunk["chunk_id"]
            tokens = _tokenize(chunk["text"])
            counts = Counter(tokens)
            tf[cid] = counts
            lengths[cid] = len(tokens)
            for term in counts.keys():
                df[term] += 1

        avg_len = (sum(lengths.values()) / len(lengths)) if lengths else 0
        return {
            "chunks": chunks,
            "tf": {cid: dict(c) for cid, c in tf.items()},
            "df": dict(df),
            "lengths": lengths,
            "avg_len": avg_len,
            "doc_count": len(chunks),
        }


class RetrieveChunksTool:
    name = "retrieve_chunks"

    def run(self, query: str, index: dict[str, Any], top_k: int = 5) -> list[dict[str, Any]]:
        query_terms = _tokenize(query)
        if not query_terms:
            return []

        chunks = {chunk["chunk_id"]: chunk for chunk in index.get("chunks", [])}
        tf = index.get("tf", {})
        df = index.get("df", {})
        lengths = index.get("lengths", {})
        avg_len = index.get("avg_len", 0) or 1
        doc_count = index.get("doc_count", 0) or 1

        k1 = 1.5
        b = 0.75
        scored: list[tuple[float, str]] = []

        for cid, term_counts in tf.items():
            score = 0.0
            doc_len = lengths.get(cid, 1)
            for term in query_terms:
                freq = term_counts.get(term, 0)
                if freq == 0:
                    continue
                dfi = df.get(term, 0)
                idf = math.log(1 + (doc_count - dfi + 0.5) / (dfi + 0.5))
                denom = freq + k1 * (1 - b + b * (doc_len / avg_len))
                score += idf * ((freq * (k1 + 1)) / denom)
            if score > 0:
                scored.append((score, cid))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        for score, cid in scored[:top_k]:
            chunk = chunks[cid]
            row = {"chunk_id": cid, "score": round(score, 6), "text": chunk["text"]}
            if "start" in chunk:
                row["start"] = chunk["start"]
            if "end" in chunk:
                row["end"] = chunk["end"]
            if "section_no" in chunk:
                row["section_no"] = chunk.get("section_no")
                row["title"] = chunk.get("title")
                row["anchors"] = chunk.get("anchors", [])
            results.append(row)
        return results
