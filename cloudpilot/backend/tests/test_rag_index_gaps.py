import pytest

import app.rag.index as index_module
from app.rag.index import build_index, get_index, reset_index


def test_build_index_raises_when_no_documents_found(monkeypatch) -> None:
    monkeypatch.setattr(index_module, "load_knowledge_chunks", lambda: [])

    with pytest.raises(RuntimeError, match="No knowledge base documents found"):
        build_index()


def test_reset_index_forces_a_rebuild() -> None:
    first = get_index()
    second = get_index()
    assert first is second  # cached, same process-wide singleton

    reset_index()
    third = get_index()

    assert third is not first
    assert third.chunks == first.chunks  # same underlying docs, freshly rebuilt
