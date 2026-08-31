"""Loads the markdown knowledge base and splits each document into
retrievable chunks — one per `##` section, with the document's `#` title
carried along as source metadata. Sections are the right chunk granularity
here: each one is a self-contained piece of advice, short enough to embed
well and long enough to actually answer a query on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DOCUMENTS_DIR = Path(__file__).parent / "documents"


@dataclass(frozen=True)
class KnowledgeChunk:
    doc_title: str
    doc_filename: str
    section_heading: str
    text: str


def _load_document_chunks(path: Path) -> list[KnowledgeChunk]:
    lines = path.read_text(encoding="utf-8").splitlines()

    has_title = bool(lines) and lines[0].startswith("# ")
    title = lines[0][2:].strip() if has_title else path.stem
    body_lines = lines[1:] if has_title else lines

    chunks: list[KnowledgeChunk] = []
    current_heading = "Overview"
    current_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append(
                KnowledgeChunk(
                    doc_title=title,
                    doc_filename=path.name,
                    section_heading=current_heading,
                    text=text,
                )
            )

    for line in body_lines:
        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()

    return chunks


def load_knowledge_chunks() -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for path in sorted(DOCUMENTS_DIR.glob("*.md")):
        chunks.extend(_load_document_chunks(path))
    return chunks
