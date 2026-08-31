"""search_optimization_knowledge: real semantic search over the markdown
knowledge base (`app/rag/`), using local embeddings + FAISS — no external
API call, no LLM involved in retrieval itself. Results carry an explicit
`source` citation (document title + section) so a caller can quote where
its advice came from rather than presenting it as its own.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.rag.retriever import search_knowledge
from app.tools.base import run_tool

TOOL_SEARCH_OPTIMIZATION_KNOWLEDGE = "search_optimization_knowledge"


class SearchOptimizationKnowledgeInput(BaseModel):
    query: str
    top_k: int = 3


class KnowledgeSnippet(BaseModel):
    source: str
    content: str
    score: float


class SearchOptimizationKnowledgeOutput(BaseModel):
    results: list[KnowledgeSnippet]
    stub: bool = False


def search_optimization_knowledge(
    db: Session, *, agent_name: str, session_id: str, input: SearchOptimizationKnowledgeInput
) -> SearchOptimizationKnowledgeOutput:
    def _impl() -> SearchOptimizationKnowledgeOutput:
        chunks = search_knowledge(input.query, top_k=input.top_k)
        return SearchOptimizationKnowledgeOutput(
            results=[
                KnowledgeSnippet(
                    source=f"{c.doc_title} — {c.section_heading}",
                    content=c.text,
                    score=c.score,
                )
                for c in chunks
            ]
        )

    return run_tool(
        db,
        agent_name=agent_name,
        session_id=session_id,
        tool_name=TOOL_SEARCH_OPTIMIZATION_KNOWLEDGE,
        input_model=input,
        fn=_impl,
    )
