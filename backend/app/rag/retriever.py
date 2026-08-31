"""search_knowledge(): the real retrieval function — embeds the query
locally, searches the FAISS index, and returns the top-k chunks with
their source (document title, filename, section) and similarity score.
This is what `search_optimization_knowledge` (Phase 7's stub) now calls.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.rag.embeddings import embed_texts
from app.rag.index import get_index


class RetrievedChunk(BaseModel):
    doc_title: str
    doc_filename: str
    section_heading: str
    text: str
    score: float


def search_knowledge(query: str, top_k: int = 3) -> list[RetrievedChunk]:
    knowledge_index = get_index()
    query_embedding = embed_texts([query])

    k = min(top_k, len(knowledge_index.chunks))
    scores, indices = knowledge_index.index.search(query_embedding, k)

    results: list[RetrievedChunk] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        chunk = knowledge_index.chunks[idx]
        results.append(
            RetrievedChunk(
                doc_title=chunk.doc_title,
                doc_filename=chunk.doc_filename,
                section_heading=chunk.section_heading,
                text=chunk.text,
                score=float(score),
            )
        )
    return results
