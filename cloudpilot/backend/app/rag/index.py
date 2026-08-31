"""Builds a FAISS index over the knowledge base chunks, lazily and once
per process — the doc set is small (a handful of markdown files, a few
dozen sections), so embedding all of it takes a couple of seconds and
doesn't need disk persistence or incremental updates.
"""

from __future__ import annotations

from dataclasses import dataclass

import faiss

from app.rag.embeddings import embed_texts
from app.rag.loader import KnowledgeChunk, load_knowledge_chunks


@dataclass
class KnowledgeIndex:
    chunks: list[KnowledgeChunk]
    index: faiss.Index


_index: KnowledgeIndex | None = None


def build_index() -> KnowledgeIndex:
    chunks = load_knowledge_chunks()
    if not chunks:
        raise RuntimeError("No knowledge base documents found under app/rag/documents/")

    # Prefixing with title + heading gives the embedding model useful
    # context beyond the section body alone.
    texts = [f"{c.doc_title} — {c.section_heading}\n{c.text}" for c in chunks]
    embeddings = embed_texts(texts)

    index = faiss.IndexFlatIP(embeddings.shape[1])  # inner product == cosine sim (vectors are normalized)
    index.add(embeddings)

    return KnowledgeIndex(chunks=chunks, index=index)


def get_index() -> KnowledgeIndex:
    global _index
    if _index is None:
        _index = build_index()
    return _index


def reset_index() -> None:
    """Test-only: force the next get_index() call to rebuild from disk."""
    global _index
    _index = None
