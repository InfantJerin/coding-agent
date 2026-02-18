from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from llm.providers import LLMClient

SECTION_RE = re.compile(r"^(?:Section|SECTION)\s+(\d+(?:\.\d+)*)\s*[:.-]?\s*(.*)$")
NUMERIC_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){1,5})\s+([A-Za-z][A-Za-z0-9 ,:;()'\"/&-]{2,})$")
ARTICLE_RE = re.compile(r"^(?:Article|ARTICLE)\s+([IVXLCM]+|[A-Z])\s*[:.-]?\s*(.*)$")

DEF_RE = re.compile(r"[\"“]([A-Za-z][A-Za-z0-9\s\-/()]+)[\"”]\s+means\s+(.+)", re.IGNORECASE)
DEF_RE_UNQUOTED = re.compile(r"^([A-Z][A-Za-z0-9\s\-/()]{2,80})\s+means\s+(.+)$", re.IGNORECASE)

SECTION_REF_RE = re.compile(r"Section\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
ARTICLE_REF_RE = re.compile(r"Article\s+([IVXLCM]+|[A-Z])", re.IGNORECASE)
DEFINED_REF_RE = re.compile(r"as\s+defined\s+in\s+[\"“]([^\"”]+)[\"”]", re.IGNORECASE)

TOC_LINE_RE = re.compile(
    r"^(?P<label>(?:Section\s+)?\d+(?:\.\d+)*|Article\s+[IVXLCM]+)?\s*(?P<title>[A-Za-z].*?)\s+\.{2,}\s*(?P<page>\d{1,4})$",
    re.IGNORECASE,
)
TOC_PAGE_FALLBACK_RE = re.compile(r"^(?P<title>[A-Za-z].*?)\s+(?P<page>\d{1,4})$")


def _extract_pdf_pages_and_outlines(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]

        outlines: list[dict[str, Any]] = []
        raw_outline = getattr(reader, "outline", None)
        if raw_outline:

            def walk(nodes: list[Any], level: int) -> None:
                for node in nodes:
                    if isinstance(node, list):
                        walk(node, level + 1)
                        continue
                    title = str(getattr(node, "title", "") or "").strip()
                    if not title:
                        continue
                    page_no: int | None = None
                    try:
                        page_no = reader.get_destination_page_number(node) + 1
                    except Exception:
                        pass
                    outlines.append({"title": title, "page": page_no, "level": level})

            walk(list(raw_outline), 1)

        if pages:
            return pages, outlines
    except Exception:
        pass

    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        completed = subprocess.run([pdftotext, str(path), "-"], text=True, capture_output=True, check=False)
        if completed.returncode == 0 and completed.stdout.strip():
            parts = [part.strip() for part in completed.stdout.split("\f")]
            pages = [part for part in parts if part]
            if pages:
                return pages, []

    if os.getenv("PDF_ALLOW_BINARY_FALLBACK", "").strip() == "1":
        return [path.read_bytes().decode("utf-8", errors="ignore")], []

    raise RuntimeError("No PDF extractor available. Install `pypdf` (recommended) or `pdftotext`.")


def _extract_text_pages(path: Path) -> list[str]:
    text = path.read_text(errors="ignore")
    page_splits = re.split(r"\n\s*\[PAGE\s+\d+\]\s*\n", text)
    cleaned = [part.strip() for part in page_splits if part.strip()]
    return cleaned if cleaned else [text]


def _normalize_section_key(value: str) -> str:
    return value.strip().lower().replace(" ", "")


def _normalize_query_tokens(value: str) -> list[str]:
    stop = {"what", "which", "when", "where", "how", "the", "is", "are", "does", "do", "for", "and", "any", "date"}
    return [tok.lower() for tok in re.findall(r"[a-zA-Z0-9]{2,}", value) if tok.lower() not in stop]


def _detect_heading(block: str) -> dict[str, Any] | None:
    section_match = SECTION_RE.match(block)
    if section_match:
        section_no = section_match.group(1)
        title = section_match.group(2).strip() or f"Section {section_no}"
        return {"kind": "section", "section_no": section_no, "title": title, "level": section_no.count(".") + 1}

    numeric_match = NUMERIC_HEADING_RE.match(block)
    if numeric_match:
        section_no = numeric_match.group(1)
        title = numeric_match.group(2).strip()
        return {"kind": "section", "section_no": section_no, "title": title, "level": section_no.count(".") + 1}

    article_match = ARTICLE_RE.match(block)
    if article_match:
        article_no = article_match.group(1).strip().upper()
        title = article_match.group(2).strip() or f"Article {article_no}"
        return {"kind": "article", "section_no": f"ARTICLE-{article_no}", "title": title, "level": 1}

    return None


def _detect_definition(block: str) -> tuple[str, str] | None:
    quoted = DEF_RE.search(block)
    if quoted:
        return quoted.group(1).strip(), quoted.group(2).strip()
    unquoted = DEF_RE_UNQUOTED.match(block)
    if unquoted:
        term = unquoted.group(1).strip()
        text = unquoted.group(2).strip()
        if len(term.split()) <= 8:
            return term, text
    return None


def _extract_toc_candidates(doc: dict[str, Any], max_pages: int = 8) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    total = min(max_pages, int(doc["total_pages"]))
    for page_idx in range(total):
        page_num = page_idx + 1
        for line in [ln.strip() for ln in doc["pages"][page_idx].splitlines() if ln.strip()]:
            m = TOC_LINE_RE.match(line)
            if m:
                label = (m.group("label") or "").strip()
                title = m.group("title").strip()
                page = int(m.group("page"))
                section_no = ""
                if label:
                    if label.lower().startswith("section"):
                        section_no = label.split(None, 1)[1]
                    elif label.lower().startswith("article"):
                        section_no = f"ARTICLE-{label.split(None, 1)[1].upper()}"
                    else:
                        section_no = label
                candidates.append({"section_no": section_no, "title": title, "toc_page": page_num, "target_page": page})
                continue

            # relaxed fallback for lines with trailing page number
            mf = TOC_PAGE_FALLBACK_RE.match(line)
            if mf and len(line) > 12:
                title = mf.group("title").strip()
                page = int(mf.group("page"))
                if title.lower().startswith(("section ", "article ")):
                    h = _detect_heading(title)
                    sec = h["section_no"] if h else ""
                    ttl = h["title"] if h else title
                    candidates.append({"section_no": sec, "title": ttl, "toc_page": page_num, "target_page": page})

    # de-dup by (section_no,title,target_page)
    dedup: dict[tuple[str, str, int], dict[str, Any]] = {}
    for c in candidates:
        key = (_normalize_section_key(c["section_no"] or c["title"]), c["title"].lower(), int(c["target_page"]))
        dedup[key] = c
    return list(dedup.values())


def _verify_toc_assignments(doc_id: str, sections: list[dict[str, Any]], anchors: dict[str, dict[str, Any]], radius: int = 2) -> list[dict[str, Any]]:
    # PageIndex-like verify/correct loop: check heading text near predicted page and adjust.
    anchor_by_page_block: dict[tuple[int, int], str] = {}
    blocks_by_page: dict[int, list[tuple[int, str, str]]] = {}
    for anchor, data in anchors.items():
        if data["doc_id"] != doc_id:
            continue
        page = int(data["page"])
        block = int(data["block"])
        anchor_by_page_block[(page, block)] = anchor
        blocks_by_page.setdefault(page, []).append((block, data["text"], anchor))

    for page in list(blocks_by_page.keys()):
        blocks_by_page[page].sort(key=lambda item: item[0])

    corrected: list[dict[str, Any]] = []
    for section in sections:
        predicted = int(section["page_start"])
        target_no = _normalize_section_key(section.get("section_no", ""))
        target_title = section.get("title", "").lower()

        best: tuple[int, str, int] | None = None  # dist, anchor, page
        for candidate_page in range(max(1, predicted - radius), predicted + radius + 1):
            for _, text, anchor in blocks_by_page.get(candidate_page, []):
                h = _detect_heading(text)
                if not h:
                    continue
                hn = _normalize_section_key(h["section_no"])
                title_match = target_title and target_title[:25] in h["title"].lower()
                no_match = target_no and (target_no == hn)
                if no_match or title_match:
                    dist = abs(candidate_page - predicted)
                    if best is None or dist < best[0]:
                        best = (dist, anchor, candidate_page)
        if best:
            _, anchor, resolved_page = best
            section = {
                **section,
                "anchor": anchor,
                "page_start": resolved_page,
                "verification": "corrected" if resolved_page != predicted else "verified",
            }
        else:
            section = {**section, "verification": "unverified"}
        corrected.append(section)
    return corrected


def _section_sort_key(section_no: str) -> tuple[int, tuple[int, ...], str]:
    if section_no.startswith("ARTICLE-"):
        article = section_no.split("-", 1)[1].strip().upper()
        roman = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total = 0
        prev = 0
        for ch in reversed(article):
            value = roman.get(ch, 0)
            if value < prev:
                total -= value
            else:
                total += value
                prev = value
        return (0, (total or 0,), section_no)

    numeric = re.findall(r"\d+", section_no)
    if numeric:
        return (1, tuple(int(part) for part in numeric), section_no)
    return (2, (10**9,), section_no)


def _build_section_tree(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sections:
        return []

    by_id: dict[str, dict[str, Any]] = {}
    for section in sections:
        by_id[section["id"]] = {
            "id": section["id"],
            "node_id": "",
            "doc_id": section["doc_id"],
            "section_no": section["section_no"],
            "title": section["title"],
            "level": int(section.get("level", 1)),
            "start_index": int(section.get("page_start", 1)),
            "end_index": int(section.get("page_end", section.get("page_start", 1))),
            "anchor": section["anchor"],
            "source": section.get("source", "text"),
            "summary": section.get("summary", ""),
            "key_events": section.get("key_events", []),
            "children": [],
        }

    roots: list[dict[str, Any]] = []
    current_parent_by_level: dict[int, dict[str, Any]] = {}
    ordered = sorted(
        sections,
        key=lambda s: (
            s["doc_id"],
            int(s.get("page_start", 1)),
            int(s.get("block_start", 1)),
            _section_sort_key(s["section_no"]),
        ),
    )

    for section in ordered:
        node = by_id[section["id"]]
        level = max(1, int(section.get("level", 1)))
        parent = current_parent_by_level.get(level - 1)
        if parent and parent["doc_id"] == node["doc_id"]:
            parent["children"].append(node)
        else:
            roots.append(node)
        current_parent_by_level[level] = node
        for deeper in list(current_parent_by_level.keys()):
            if deeper > level:
                del current_parent_by_level[deeper]

    counter = 1

    def assign(nodes: list[dict[str, Any]]) -> None:
        nonlocal counter
        for node in nodes:
            node["node_id"] = f"N{counter:05d}"
            counter += 1
            assign(node["children"])

    assign(roots)
    return roots


def _flatten_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(items: list[dict[str, Any]]) -> None:
        for node in items:
            out.append(node)
            walk(node.get("children", []))

    walk(nodes)
    return out


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass

    match = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        return []
    return []


def _build_section_summary(doc: dict[str, Any], section: dict[str, Any]) -> tuple[str, list[str]]:
    start = max(1, int(section.get("page_start", 1)))
    end = min(int(doc["total_pages"]), int(section.get("page_end", start)))

    lines: list[str] = []
    for page in range(start, end + 1):
        page_text = doc["pages"][page - 1]
        for raw in page_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if _detect_heading(line):
                continue
            lines.append(line)

    if not lines:
        return "", []

    summary = " ".join(lines)[:320]
    key_events: list[str] = []
    event_tokens = (
        "covenant",
        "default",
        "maturity",
        "interest",
        "payment",
        "ratio",
        "margin",
        "liquidity",
        "leverage",
    )
    for line in lines:
        low = line.lower()
        if any(token in low for token in event_tokens):
            key_events.append(line[:220])
        if len(key_events) >= 5:
            break
    return summary, key_events


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
                pages, outlines = _extract_pdf_pages_and_outlines(path)
            else:
                pages = _extract_text_pages(path)
                outlines = []

            docs.append(
                {
                    "doc_id": doc_id,
                    "path": str(path),
                    "name": path.name,
                    "pages": pages,
                    "total_pages": len(pages),
                    "outlines": outlines,
                }
            )
        return {"documents": docs}


class BuildDocMapTool:
    name = "build_doc_map"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    def _build_llm_sections(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        if self.llm_client is None:
            return []

        previews: list[str] = []
        for page_num, text in enumerate(doc["pages"][: min(12, len(doc["pages"]))], start=1):
            clean = " ".join(text.split())
            if not clean:
                continue
            previews.append(f"[PAGE {page_num}] {clean[:1200]}")

        if not previews:
            return []

        system_prompt = (
            "Extract a basic legal-document table of contents from page previews. "
            "Return JSON array only. Each item must include: "
            "section_no, title, page_start, level."
        )
        user_prompt = (
            "Document previews:\n"
            + "\n\n".join(previews)
            + "\n\nReturn strictly JSON array, no markdown."
        )

        try:
            raw = self.llm_client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception:
            return []

        rows = _extract_json_array(raw)
        out: list[dict[str, Any]] = []
        for idx, row in enumerate(rows, start=1):
            section_no = str(row.get("section_no", "")).strip() or f"LLM-{idx}"
            title = str(row.get("title", "")).strip() or f"Section {section_no}"
            try:
                page_start = int(row.get("page_start", 1))
            except Exception:
                page_start = 1
            if page_start < 1:
                page_start = 1
            try:
                level = int(row.get("level", 1))
            except Exception:
                level = 1
            out.append(
                {
                    "id": f"{doc['doc_id']}:section:{section_no}:llm:{idx}",
                    "doc_id": doc["doc_id"],
                    "section_no": section_no,
                    "title": title,
                    "level": max(1, level),
                    "page_start": min(page_start, int(doc["total_pages"])),
                    "page_end": min(page_start, int(doc["total_pages"])),
                    "anchor": "",
                    "block_start": 1,
                    "source": "llm",
                }
            )
        return out

    def run(self, document_store: dict[str, Any], parse_strategy: str = "legal_contract") -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        definitions: list[dict[str, Any]] = []
        anchors: dict[str, dict[str, Any]] = {}
        xrefs: list[dict[str, Any]] = []

        section_index: dict[str, str] = {}
        definition_index: dict[str, str] = {}
        page_first_anchor: dict[tuple[str, int], str] = {}

        xref_counter = 0
        pending_xrefs: list[dict[str, Any]] = []

        for doc in document_store["documents"]:
            doc_id = doc["doc_id"]
            if parse_strategy != "legal_contract":
                for page_num, page_text in enumerate(doc["pages"], start=1):
                    raw_blocks = [line.strip() for line in page_text.splitlines() if line.strip()]
                    if not raw_blocks:
                        raw_blocks = [f"Page {page_num}"]
                    for block_num, block in enumerate(raw_blocks, start=1):
                        anchor = f"{doc_id}:p{page_num}:b{block_num}"
                        page_first_anchor.setdefault((doc_id, page_num), anchor)
                        anchors[anchor] = {
                            "doc_id": doc_id,
                            "page": page_num,
                            "block": block_num,
                            "text": block,
                        }
                    first_anchor = page_first_anchor[(doc_id, page_num)]
                    title = raw_blocks[0][:100].strip() or f"Page {page_num}"
                    sections.append(
                        {
                            "id": f"{doc_id}:section:P{page_num}:generic",
                            "doc_id": doc_id,
                            "section_no": f"P{page_num}",
                            "title": title,
                            "level": 1,
                            "page_start": page_num,
                            "page_end": page_num,
                            "anchor": first_anchor,
                            "block_start": 1,
                            "source": "generic",
                        }
                    )
                continue

            # TOC-first candidates
            toc_candidates = _extract_toc_candidates(doc)
            for idx, entry in enumerate(toc_candidates, start=1):
                section_no = entry.get("section_no") or f"TOC-{idx}"
                sections.append(
                    {
                        "id": f"{doc_id}:section:{section_no}:toc:{idx}",
                        "doc_id": doc_id,
                        "section_no": section_no,
                        "title": entry["title"],
                        "level": max(1, section_no.count(".") + 1) if not section_no.startswith("ARTICLE-") else 1,
                        "page_start": int(entry["target_page"]),
                        "page_end": int(entry["target_page"]),
                        "anchor": "",
                        "block_start": 1,
                        "source": "toc",
                    }
                )

            # If TOC isn't detectable, ask LLM for a basic index proposal.
            if not toc_candidates:
                sections.extend(self._build_llm_sections(doc))

            for page_num, page_text in enumerate(doc["pages"], start=1):
                raw_blocks = [line.strip() for line in page_text.splitlines() if line.strip()]
                for block_num, block in enumerate(raw_blocks, start=1):
                    anchor = f"{doc_id}:p{page_num}:b{block_num}"
                    page_first_anchor.setdefault((doc_id, page_num), anchor)
                    anchors[anchor] = {
                        "doc_id": doc_id,
                        "page": page_num,
                        "block": block_num,
                        "text": block,
                    }

                    heading = _detect_heading(block)
                    if heading:
                        section_no = heading["section_no"]
                        sections.append(
                            {
                                "id": f"{doc_id}:section:{section_no}:text:{page_num}:{block_num}",
                                "doc_id": doc_id,
                                "section_no": section_no,
                                "title": heading["title"],
                                "level": heading["level"],
                                "page_start": page_num,
                                "page_end": page_num,
                                "anchor": anchor,
                                "block_start": block_num,
                                "source": "text",
                            }
                        )
                        section_index[f"{doc_id}:{_normalize_section_key(section_no)}"] = anchor

                    definition = _detect_definition(block)
                    if definition:
                        term, term_text = definition
                        definitions.append(
                            {
                                "id": f"{doc_id}:def:{term.lower()}",
                                "doc_id": doc_id,
                                "term": term,
                                "anchor": anchor,
                                "text": term_text,
                            }
                        )
                        definition_index[f"{doc_id}:{term.lower()}"] = anchor

                    for ref in SECTION_REF_RE.findall(block):
                        pending_xrefs.append({"id": f"xref-{xref_counter}", "from_anchor": anchor, "ref_type": "section_ref", "target_text": ref})
                        xref_counter += 1
                    for ref in ARTICLE_REF_RE.findall(block):
                        pending_xrefs.append({"id": f"xref-{xref_counter}", "from_anchor": anchor, "ref_type": "article_ref", "target_text": ref})
                        xref_counter += 1
                    for ref in DEFINED_REF_RE.findall(block):
                        pending_xrefs.append({"id": f"xref-{xref_counter}", "from_anchor": anchor, "ref_type": "definition_ref", "target_text": ref.strip()})
                        xref_counter += 1

            # Outline entries as additional section signals.
            for idx, outline in enumerate(doc.get("outlines", []), start=1):
                page_no = outline.get("page")
                if not isinstance(page_no, int) or page_no < 1:
                    continue
                anchor = page_first_anchor.get((doc_id, page_no), "")
                raw_title = str(outline.get("title", "")).strip()
                heading = _detect_heading(raw_title)
                section_no = heading["section_no"] if heading else f"OUTLINE-{idx}"
                title = heading["title"] if heading else raw_title
                sections.append(
                    {
                        "id": f"{doc_id}:section:{section_no}:outline:{idx}",
                        "doc_id": doc_id,
                        "section_no": section_no,
                        "title": title,
                        "level": int(outline.get("level", 1)),
                        "page_start": page_no,
                        "page_end": page_no,
                        "anchor": anchor,
                        "block_start": 1,
                        "source": "outline",
                    }
                )
                if anchor:
                    section_index.setdefault(f"{doc_id}:{_normalize_section_key(section_no)}", anchor)

            # Verify/correct TOC page assignments now that anchors exist.
            doc_sections = [s for s in sections if s["doc_id"] == doc_id]
            corrected = _verify_toc_assignments(doc_id, doc_sections, anchors)
            sections = [s for s in sections if s["doc_id"] != doc_id] + corrected

        # choose best representative per normalized section key
        source_priority = {"toc": 0, "outline": 1, "llm": 2, "generic": 2, "text": 3}
        picked_sections: dict[tuple[str, str], dict[str, Any]] = {}
        for section in sections:
            key = (section["doc_id"], _normalize_section_key(section["section_no"]))
            current = picked_sections.get(key)
            if current is None:
                picked_sections[key] = section
                continue
            cur_p = source_priority.get(current.get("source", "text"), 99)
            new_p = source_priority.get(section.get("source", "text"), 99)
            if new_p > cur_p:
                picked_sections[key] = section
            elif new_p == cur_p and int(section.get("page_start", 1)) < int(current.get("page_start", 1)):
                picked_sections[key] = section

        sections = list(picked_sections.values())

        # ensure anchors for TOC/outline-only sections
        for section in sections:
            if section.get("anchor"):
                section_index[f"{section['doc_id']}:{_normalize_section_key(section['section_no'])}"] = section["anchor"]
                continue
            doc_id = section["doc_id"]
            page_start = int(section["page_start"])
            candidate = next(
                (
                    anchor
                    for anchor, data in anchors.items()
                    if data["doc_id"] == doc_id and int(data["page"]) == page_start and int(data["block"]) == 1
                ),
                "",
            )
            section["anchor"] = candidate
            if candidate:
                section_index[f"{doc_id}:{_normalize_section_key(section['section_no'])}"] = candidate

        # Resolve xrefs (pass 2)
        for ref in pending_xrefs:
            from_anchor = ref["from_anchor"]
            from_doc = anchors[from_anchor]["doc_id"]
            resolved_anchor: str | None = None
            if ref["ref_type"] in {"section_ref", "article_ref"}:
                raw_target = ref["target_text"].strip()
                if ref["ref_type"] == "article_ref":
                    raw_target = f"ARTICLE-{raw_target}"
                section_key = f"{from_doc}:{_normalize_section_key(raw_target)}"
                resolved_anchor = section_index.get(section_key)
            elif ref["ref_type"] == "definition_ref":
                def_key = f"{from_doc}:{ref['target_text'].strip().lower()}"
                resolved_anchor = definition_index.get(def_key)
            xrefs.append({**ref, "resolved_anchor": resolved_anchor})

        sections.sort(key=lambda s: (s["doc_id"], int(s.get("page_start", 1)), int(s.get("block_start", 1))))

        max_page_by_doc = {d["doc_id"]: int(d["total_pages"]) for d in document_store["documents"]}
        for idx, section in enumerate(sections):
            doc_id = section["doc_id"]
            next_section = next((sections[j] for j in range(idx + 1, len(sections)) if sections[j]["doc_id"] == doc_id), None)
            if next_section:
                section["page_end"] = max(int(section["page_start"]), int(next_section["page_start"]) - 1)
            else:
                section["page_end"] = max_page_by_doc.get(doc_id, int(section["page_start"]))

        # Add section-level summaries/key events for index navigation.
        docs_by_id = {d["doc_id"]: d for d in document_store["documents"]}
        for section in sections:
            doc = docs_by_id.get(section["doc_id"])
            if not doc:
                continue
            summary, key_events = _build_section_summary(doc, section)
            section["summary"] = summary
            section["key_events"] = key_events

        sections_by_doc: dict[str, list[dict[str, Any]]] = {}
        for section in sections:
            sections_by_doc.setdefault(section["doc_id"], []).append(section)
        section_tree_by_doc = {doc_id: _build_section_tree(doc_sections) for doc_id, doc_sections in sections_by_doc.items()}

        return {
            "document_store": document_store,
            "sections": sections,
            "section_tree": section_tree_by_doc,
            "definitions": definitions,
            "anchors": anchors,
            "xrefs": xrefs,
        }


class OpenDocTool:
    name = "open_doc"

    def run(self, doc_map: dict[str, Any], doc_id: str) -> dict[str, Any]:
        for doc in doc_map["document_store"]["documents"]:
            if doc["doc_id"] == doc_id:
                return {"doc_id": doc_id, "name": doc["name"], "path": doc["path"], "total_pages": doc["total_pages"]}
        raise KeyError(f"Unknown doc_id: {doc_id}")


class GotoPageTool:
    name = "goto_page"

    def run(self, doc_map: dict[str, Any], doc_id: str, page: int) -> dict[str, Any]:
        for doc in doc_map["document_store"]["documents"]:
            if doc["doc_id"] != doc_id:
                continue
            if page < 1 or page > doc["total_pages"]:
                raise ValueError(f"Page out of range for {doc_id}: {page}")
            return {"doc_id": doc_id, "page": page, "text": doc["pages"][page - 1]}
        raise KeyError(f"Unknown doc_id: {doc_id}")


class OpenAtAnchorTool:
    name = "open_at_anchor"

    def run(self, doc_map: dict[str, Any], anchor: str) -> dict[str, Any]:
        if anchor not in doc_map["anchors"]:
            raise KeyError(f"Unknown anchor: {anchor}")
        return {"anchor": anchor, **doc_map["anchors"][anchor]}


class ReadSpanTool:
    name = "read_span"

    def run(self, doc_map: dict[str, Any], anchor: str | None = None, page_range: dict[str, int] | None = None, doc_id: str | None = None) -> dict[str, Any]:
        if anchor:
            data = doc_map["anchors"].get(anchor)
            if not data:
                raise KeyError(f"Unknown anchor: {anchor}")
            return {
                "doc_id": data["doc_id"],
                "anchors": [anchor],
                "text": data["text"],
                "spans": [{"anchor": anchor, "page": data["page"], "block": data["block"], "char_start": 0, "char_end": len(data["text"])}],
            }

        if page_range:
            # Default doc_id to the first document when not provided
            if not doc_id:
                docs = doc_map.get("document_store", {}).get("documents", [])
                if len(docs) == 1:
                    doc_id = docs[0]["doc_id"]
                else:
                    raise ValueError("Provide either anchor or (doc_id and page_range)")

            start = int(page_range.get("start", 1))
            end = int(page_range.get("end", start))
            if end < start:
                raise ValueError("page_range end must be >= start")

            doc = next((d for d in doc_map["document_store"]["documents"] if d["doc_id"] == doc_id), None)
            if not doc:
                raise KeyError(f"Unknown doc_id: {doc_id}")

            collected: list[str] = []
            spans: list[dict[str, Any]] = []
            for page in range(start, min(end, doc["total_pages"]) + 1):
                text = doc["pages"][page - 1]
                collected.append(f"[PAGE {page}]\n{text}")
                spans.append({"page": page, "char_start": 0, "char_end": len(text)})
            return {"doc_id": doc_id, "anchors": [], "text": "\n\n".join(collected), "spans": spans}

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
            # Financial structure terms
            if any(t in q_lower for t in ("facility", "facilities", "tranche", "commitment")) and \
               any(t in low for t in ("facility", "facilities", "tranche", "commitment")):
                score += 3
            if any(t in q_lower for t in ("interest", "rate", "margin", "sofr")) and \
               any(t in low for t in ("interest", "rate", "margin", "sofr")):
                score += 3
            if any(t in q_lower for t in ("repayment", "prepayment", "amortization")) and \
               any(t in low for t in ("repayment", "prepayment", "amortization")):
                score += 3
            return score

        candidates: list[dict[str, Any]] = []

        if scope in {"doc", "section"}:
            # Tree-first (PageIndex-inspired): score nodes before raw blocks.
            for doc_id, roots in doc_map.get("section_tree", {}).items():
                for node in _flatten_tree(roots):
                    # Skip TOC index entries — their anchor points back to the TOC page,
                    # not the actual content page, so they produce useless results.
                    section_no = node.get("section_no", "")
                    if str(section_no).startswith("TOC-"):
                        continue
                    anchor = node.get("anchor")
                    anchor_data = doc_map["anchors"].get(anchor, {}) if anchor else {}
                    text = f"{section_no} {node.get('title','')} {anchor_data.get('text','')}"
                    if node.get("summary"):
                        text = f"{text} {node['summary']}"
                    if node.get("key_events"):
                        text = f"{text} {' '.join(node['key_events'])}"
                    score = score_text(text)
                    if score > 0:
                        candidates.append(
                            {
                                "type": "section",
                                "score": score,
                                "anchor": anchor,
                                "doc_id": doc_id,
                                "section_no": section_no,
                                "title": node.get("title"),
                                # page_start/page_end let the LLM navigate directly to content
                                "page_start": node.get("start_index"),
                                "page_end": node.get("end_index"),
                                "text": anchor_data.get("text", ""),
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
                        {"type": "block", "score": score, "anchor": anchor, "doc_id": data["doc_id"], "text": data["text"]}
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
                        return {"resolved": True, "anchor": ref["resolved_anchor"], "ref": ref}
                    return {"resolved": False, "ref": ref}
            raise KeyError(f"Unknown ref_id: {ref_id}")

        if target_text and doc_id:
            normalized_target = _normalize_section_key(target_text)
            sec_match = re.search(r"(\d+(?:\.\d+)*)", target_text)
            article_match = re.search(r"(?:article)\s+([ivxlcm]+|[a-z])", target_text, re.IGNORECASE)
            for section in doc_map["sections"]:
                if section["doc_id"] != doc_id:
                    continue
                section_key = _normalize_section_key(section["section_no"])
                if normalized_target in section_key or section_key in normalized_target:
                    return {"resolved": True, "anchor": section["anchor"], "ref": {"ref_type": "section_ref", "target_text": target_text}}
                if sec_match and section["section_no"] == sec_match.group(1):
                    return {"resolved": True, "anchor": section["anchor"], "ref": {"ref_type": "section_ref", "target_text": target_text}}
                if article_match and section_key == f"article-{article_match.group(1).lower()}":
                    return {"resolved": True, "anchor": section["anchor"], "ref": {"ref_type": "article_ref", "target_text": target_text}}

            term_key = target_text.strip().lower()
            for definition in doc_map["definitions"]:
                if definition["doc_id"] == doc_id and definition["term"].lower() == term_key:
                    return {"resolved": True, "anchor": definition["anchor"], "ref": {"ref_type": "definition_ref", "target_text": target_text}}

            return {"resolved": False, "ref": {"ref_type": "unknown", "target_text": target_text}}

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
            return {"found": True, "term": definition["term"], "anchor": definition["anchor"], "text": definition["text"], "doc_id": definition["doc_id"]}
        return {"found": False, "term": term}


class QuoteEvidenceTool:
    name = "quote_evidence"

    def run(self, doc_map: dict[str, Any], anchors: list[str]) -> list[dict[str, Any]]:
        quotes: list[dict[str, Any]] = []
        for anchor in anchors:
            data = doc_map["anchors"].get(anchor)
            if not data:
                continue
            quotes.append({"anchor": anchor, "doc_id": data["doc_id"], "page": data["page"], "excerpt": data["text"][:320]})
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
