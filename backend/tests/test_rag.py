from app.rag.loader import load_knowledge_chunks
from app.rag.retriever import search_knowledge


def test_load_knowledge_chunks_covers_all_five_topics() -> None:
    chunks = load_knowledge_chunks()
    titles = {c.doc_title for c in chunks}

    assert len(chunks) > 0
    assert any("Right-Sizing" in t for t in titles)
    assert any("Autoscaling" in t for t in titles)
    assert any("Storage" in t for t in titles)
    assert any("Reserved" in t for t in titles)
    assert any("Utilization" in t for t in titles)


def test_load_knowledge_chunks_have_nonempty_text_and_headings() -> None:
    chunks = load_knowledge_chunks()
    for c in chunks:
        assert c.text.strip()
        assert c.section_heading.strip()
        assert c.doc_filename.endswith(".md")


def test_search_knowledge_returns_topically_relevant_results() -> None:
    results = search_knowledge("how do I choose the right instance size for my workload?", top_k=2)

    assert len(results) == 2
    assert any("Right-Sizing" in r.doc_title for r in results)
    for r in results:
        assert 0.0 <= r.score <= 1.0 + 1e-6


def test_search_knowledge_different_queries_hit_different_docs() -> None:
    right_sizing = search_knowledge("instance sizing guidance", top_k=1)[0]
    storage = search_knowledge("moving old data to a cheaper storage tier", top_k=1)[0]
    reserved = search_knowledge("committing to reserved capacity pricing discount", top_k=1)[0]
    autoscaling = search_knowledge("autoscaling policy to avoid outages", top_k=1)[0]

    assert "Right-Sizing" in right_sizing.doc_title
    assert "Storage" in storage.doc_title
    assert "Reserved" in reserved.doc_title
    assert "Autoscaling" in autoscaling.doc_title


def test_search_knowledge_respects_top_k() -> None:
    results = search_knowledge("cloud cost optimization", top_k=5)
    assert len(results) == 5


def test_search_knowledge_results_are_ranked_by_score_descending() -> None:
    results = search_knowledge("storage tier optimization", top_k=4)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
