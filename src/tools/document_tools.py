from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


SECTION_RE = re.compile(r"^(?:Section|SECTION)\s+(\d+(?:\.\d+)*)\s*[:.-]?\s*(.*)$")
DEF_RE = re.compile(r"[\"“]([A-Za-z][A-Za-z0-9\s\-/()]+)[\"”]\s+means\s+(.+)", re.IGNORECASE)
SECTION_REF_RE = re.compile(r"Section\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
DEFINED_REF_RE = re.compile(r"as\s+defined\s+in\s+[\"“]([^\"”]+)[\"”]", re.IGNORECASE)


def _extract_pdf_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            pages.append((page.extract_text() or "").strip())
        if pages:
            return pages
    except Exception:
        pass

    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        completed = subprocess.run(
            [pdftotext, str(path), "-"],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            # We do not get reliable page splits here, so use a single-page fallback.
            return [completed.stdout]

    return [path.read_bytes().decode("utf-8", errors="ignore")]


def _extract_text_pages(path: Path) -> list[str]:
    text = path.read_text(errors="ignore")
    page_splits = re.split(r"\n\s*\[PAGE\s+\d+\]\s*\n", text)
    cleaned = [part.strip() for part in page_splits if part.strip()]
    return cleaned if cleaned else [text]


def _normalize_query_tokens(value: str) -> list[str]:
    stop = {
        "what",
        "which",
        "when",
        "where",
        "how",
        "the",
        "is",
        "are",
        "does",
        "do",
        "for",
        "and",
        "any",
        "date",
    }
    return [tok.lower() for tok in re.findall(r"[a-zA-Z0-9]{2,}", value) if tok.lower() not in stop]


class LoadDocumentsTool:
    name = "load_documents"

    def run(self, documents: list[str]) -> dict[str, Any]:
        docs: list[dict[str, Any]] = []
        for index, raw_path in enumerate(documents):
            path = Path(raw_path)
            if not path.exists():
                raise FileNotFoundError(f"Document not found: {path}")

            doc_id = f"doc-{index}"
            if path.suffix.lower() == ".pdf":
                pages = _extract_pdf_pages(path)
            else:
                pages = _extract_text_pages(path)

            docs.append(
                {
                    "doc_id": doc_id,
                    "path": str(path),
                    "name": path.name,
                    "pages": pages,
                    "total_pages": len(pages),
                }
            )
        return {"documents": docs}


class BuildDocMapTool:
    name = "build_doc_map"

    def run(self, document_store: dict[str, Any]) -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        definitions: list[dict[str, Any]] = []
        anchors: dict[str, dict[str, Any]] = {}
        xrefs: list[dict[str, Any]] = []

        section_index: dict[str, str] = {}
        definition_index: dict[str, str] = {}

        xref_counter = 0
        for doc in document_store["documents"]:
            doc_id = doc["doc_id"]
            for page_num, page_text in enumerate(doc["pages"], start=1):
                raw_blocks = [line.strip() for line in page_text.splitlines() if line.strip()]
                for block_num, block in enumerate(raw_blocks, start=1):
                    anchor = f"{doc_id}:p{page_num}:b{block_num}"
                    anchors[anchor] = {
                        "doc_id": doc_id,
                        "page": page_num,
                        "block": block_num,
                        "text": block,
                    }

                    section_match = SECTION_RE.match(block)
                    if section_match:
                        section_no = section_match.group(1)
                        title = section_match.group(2).strip() or f"Section {section_no}"
                        section_id = f"{doc_id}:section:{section_no}"
                        sections.append(
                            {
                                "id": section_id,
                                "doc_id": doc_id,
                                "section_no": section_no,
                                "title": title,
                                "level": section_no.count(".") + 1,
                                "page_start": page_num,
                                "page_end": page_num,
                                "anchor": anchor,
                            }
                        )
                        section_index[f"{doc_id}:{section_no}"] = anchor

                    def_match = DEF_RE.search(block)
                    if def_match:
                        term = def_match.group(1).strip()
                        term_text = def_match.group(2).strip()
                        definition_id = f"{doc_id}:def:{term.lower()}"
                        definitions.append(
                            {
                                "id": definition_id,
                                "doc_id": doc_id,
                                "term": term,
                                "anchor": anchor,
                                "text": term_text,
                            }
                        )
                        definition_index[f"{doc_id}:{term.lower()}"] = anchor

                    for ref in SECTION_REF_RE.findall(block):
                        xrefs.append(
                            {
                                "id": f"xref-{xref_counter}",
                                "from_anchor": anchor,
                                "ref_type": "section_ref",
                                "target_text": ref,
                                "resolved_anchor": section_index.get(f"{doc_id}:{ref}"),
                            }
                        )
                        xref_counter += 1

                    for ref in DEFINED_REF_RE.findall(block):
                        key = ref.strip().lower()
                        xrefs.append(
                            {
                                "id": f"xref-{xref_counter}",
                                "from_anchor": anchor,
                                "ref_type": "definition_ref",
                                "target_text": ref.strip(),
                                "resolved_anchor": definition_index.get(f"{doc_id}:{key}"),
                            }
                        )
                        xref_counter += 1

        return {
            "document_store": document_store,
            "sections": sections,
            "definitions": definitions,
            "anchors": anchors,
            "xrefs": xrefs,
        }


class OpenDocTool:
    name = "open_doc"

    def run(self, doc_map: dict[str, Any], doc_id: str) -> dict[str, Any]:
        for doc in doc_map["document_store"]["documents"]:
            if doc["doc_id"] == doc_id:
                return {
                    "doc_id": doc_id,
                    "name": doc["name"],
                    "path": doc["path"],
                    "total_pages": doc["total_pages"],
                }
        raise KeyError(f"Unknown doc_id: {doc_id}")


class GotoPageTool:
    name = "goto_page"

    def run(self, doc_map: dict[str, Any], doc_id: str, page: int) -> dict[str, Any]:
        for doc in doc_map["document_store"]["documents"]:
            if doc["doc_id"] != doc_id:
                continue
            if page < 1 or page > doc["total_pages"]:
                raise ValueError(f"Page out of range for {doc_id}: {page}")
            return {
                "doc_id": doc_id,
                "page": page,
                "text": doc["pages"][page - 1],
            }
        raise KeyError(f"Unknown doc_id: {doc_id}")


class OpenAtAnchorTool:
    name = "open_at_anchor"

    def run(self, doc_map: dict[str, Any], anchor: str) -> dict[str, Any]:
        if anchor not in doc_map["anchors"]:
            raise KeyError(f"Unknown anchor: {anchor}")
        data = doc_map["anchors"][anchor]
        return {"anchor": anchor, **data}


class ReadSpanTool:
    name = "read_span"

    def run(
        self,
        doc_map: dict[str, Any],
        anchor: str | None = None,
        page_range: dict[str, int] | None = None,
        doc_id: str | None = None,
    ) -> dict[str, Any]:
        if anchor:
            data = doc_map["anchors"].get(anchor)
            if not data:
                raise KeyError(f"Unknown anchor: {anchor}")
            return {
                "doc_id": data["doc_id"],
                "anchors": [anchor],
                "text": data["text"],
                "spans": [
                    {
                        "anchor": anchor,
                        "page": data["page"],
                        "block": data["block"],
                        "char_start": 0,
                        "char_end": len(data["text"]),
                    }
                ],
            }

        if page_range and doc_id:
            start = int(page_range.get("start", 1))
            end = int(page_range.get("end", start))
            if end < start:
                raise ValueError("page_range end must be >= start")

            doc = None
            for d in doc_map["document_store"]["documents"]:
                if d["doc_id"] == doc_id:
                    doc = d
                    break
            if not doc:
                raise KeyError(f"Unknown doc_id: {doc_id}")

            collected: list[str] = []
            spans: list[dict[str, Any]] = []
            for page in range(start, min(end, doc["total_pages"]) + 1):
                text = doc["pages"][page - 1]
                collected.append(f"[PAGE {page}]\n{text}")
                spans.append(
                    {
                        "page": page,
                        "char_start": 0,
                        "char_end": len(text),
                    }
                )
            return {
                "doc_id": doc_id,
                "anchors": [],
                "text": "\n\n".join(collected),
                "spans": spans,
            }

        raise ValueError("Provide either anchor or (doc_id and page_range)")


class SearchInDocTool:
    name = "search_in_doc"

    def run(self, doc_map: dict[str, Any], query: str, scope: str = "doc", top_k: int = 8) -> list[dict[str, Any]]:
        q_tokens = _normalize_query_tokens(query)
        if not q_tokens:
            return []

        q_lower = query.lower()

        def score_text(text: str) -> int:
            low = text.lower()
            score = sum(1 for tok in q_tokens if tok in low)
            if "amount" in q_lower and "$" in text:
                score += 3
            if "maturity" in q_lower and "maturity" in low:
                score += 3
            if "covenant" in q_lower and "covenant" in low:
                score += 3
            if "default" in q_lower and "default" in low:
                score += 3
            return score

        candidates: list[dict[str, Any]] = []

        if scope in {"doc", "section"}:
            for section in doc_map["sections"]:
                anchor = section["anchor"]
                anchor_data = doc_map["anchors"][anchor]
                score = score_text(section["title"] + " " + anchor_data["text"])
                if score > 0:
                    candidates.append(
                        {
                            "type": "section",
                            "score": score,
                            "anchor": anchor,
                            "doc_id": section["doc_id"],
                            "section_no": section["section_no"],
                            "title": section["title"],
                            "text": anchor_data["text"],
                        }
                    )

        if scope in {"doc", "definition"}:
            for definition in doc_map["definitions"]:
                score = score_text(definition["term"] + " " + definition["text"])
                if score > 0:
                    candidates.append(
                        {
                            "type": "definition",
                            "score": score,
                            "anchor": definition["anchor"],
                            "doc_id": definition["doc_id"],
                            "term": definition["term"],
                            "text": definition["text"],
                        }
                    )

        if scope == "doc":
            for anchor, data in doc_map["anchors"].items():
                score = score_text(data["text"])
                if score > 0:
                    candidates.append(
                        {
                            "type": "block",
                            "score": score,
                            "anchor": anchor,
                            "doc_id": data["doc_id"],
                            "text": data["text"],
                        }
                    )

        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[:top_k]


class FollowReferenceTool:
    name = "follow_reference"

    def run(self, doc_map: dict[str, Any], ref_id: str | None = None, target_text: str | None = None, doc_id: str | None = None) -> dict[str, Any]:
        if ref_id:
            for ref in doc_map["xrefs"]:
                if ref["id"] == ref_id:
                    if ref.get("resolved_anchor"):
                        return {
                            "resolved": True,
                            "anchor": ref["resolved_anchor"],
                            "ref": ref,
                        }
                    return {"resolved": False, "ref": ref}
            raise KeyError(f"Unknown ref_id: {ref_id}")

        if target_text and doc_id:
            sec_match = re.search(r"(\d+(?:\.\d+)*)", target_text)
            if sec_match:
                sec_no = sec_match.group(1)
                for section in doc_map["sections"]:
                    if section["doc_id"] == doc_id and section["section_no"] == sec_no:
                        return {
                            "resolved": True,
                            "anchor": section["anchor"],
                            "ref": {"ref_type": "section_ref", "target_text": target_text},
                        }

            term_key = target_text.strip().lower()
            for definition in doc_map["definitions"]:
                if definition["doc_id"] == doc_id and definition["term"].lower() == term_key:
                    return {
                        "resolved": True,
                        "anchor": definition["anchor"],
                        "ref": {"ref_type": "definition_ref", "target_text": target_text},
                    }

            return {
                "resolved": False,
                "ref": {"ref_type": "unknown", "target_text": target_text},
            }

        raise ValueError("Provide ref_id or (target_text and doc_id)")


class ReadDefinitionTool:
    name = "read_definition"

    def run(self, doc_map: dict[str, Any], term: str, doc_id: str | None = None) -> dict[str, Any]:
        needle = term.strip().lower()
        for definition in doc_map["definitions"]:
            if definition["term"].lower() != needle:
                continue
            if doc_id and definition["doc_id"] != doc_id:
                continue
            return {
                "found": True,
                "term": definition["term"],
                "anchor": definition["anchor"],
                "text": definition["text"],
                "doc_id": definition["doc_id"],
            }
        return {"found": False, "term": term}


class QuoteEvidenceTool:
    name = "quote_evidence"

    def run(self, doc_map: dict[str, Any], anchors: list[str]) -> list[dict[str, Any]]:
        quotes: list[dict[str, Any]] = []
        for anchor in anchors:
            data = doc_map["anchors"].get(anchor)
            if not data:
                continue
            quotes.append(
                {
                    "anchor": anchor,
                    "doc_id": data["doc_id"],
                    "page": data["page"],
                    "excerpt": data["text"][:320],
                }
            )
        return quotes


class ConsistencyCheckTool:
    name = "consistency_check"

    def run(self, claim: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        claim_tokens = _normalize_query_tokens(claim)
        if not claim_tokens:
            return {"status": "not_supported", "score": 0.0}

        evidence_text = " ".join(item.get("excerpt", "") for item in evidence).lower()
        matched = sum(1 for tok in set(claim_tokens) if tok in evidence_text)
        ratio = matched / max(1, len(set(claim_tokens)))
        if ratio >= 0.6:
            status = "supported"
        elif ratio >= 0.3:
            status = "partially_supported"
        else:
            status = "not_supported"
        return {"status": status, "score": round(ratio, 4)}
