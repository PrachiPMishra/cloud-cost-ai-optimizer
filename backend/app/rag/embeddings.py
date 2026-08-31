"""Local embedding model — no external API, no network call per query.

A `sentence-transformers` model is downloaded once (cached under the
user's HF cache directory) and then runs entirely on-device. This is
distinct from the Gemini-backed agents: retrieval here is a deterministic
vector search, not an LLM call, and never touches GEMINI_API_KEY.
"""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """L2-normalized embeddings, so inner-product search == cosine similarity."""
    model = get_model()
    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.astype("float32")
