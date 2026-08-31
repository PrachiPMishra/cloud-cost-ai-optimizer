"""Gemini client wrapper: retry/backoff for transient errors, plus a
structured-JSON generation helper.

Every agent in this system uses the LLM only to *narrate* or *plan over*
numbers that tools have already computed — never to compute a number
itself. That split is enforced by how each agent calls this module (see
`app/agents/*_agent.py`), not by anything in here; this module's job is
just to make the Gemini call itself reliable.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_RETRIES = 4
BASE_DELAY_SECONDS = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class LLMUnavailableError(Exception):
    """Raised when Gemini has no configured key, or every retry was
    exhausted. Callers must fall back to a deterministic template — never
    invent the text the LLM would have written."""


def _client() -> genai.Client:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured")
    return genai.Client(api_key=settings.gemini_api_key)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, errors.APIError) and exc.code in RETRYABLE_STATUS_CODES:
        return True
    message = str(exc).lower()
    return any(term in message for term in ("rate limit", "quota", "unavailable", "timeout", "deadline"))


def _call_with_retry(make_request):
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return make_request()
        except Exception as exc:  # noqa: BLE001 - classify below, re-raise if not retryable
            last_error = exc
            if not _is_retryable(exc) or attempt == MAX_RETRIES - 1:
                break
            delay = BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            logger.warning(
                "Gemini call failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES,
                exc,
                delay,
            )
            time.sleep(delay)

    raise LLMUnavailableError(f"Gemini call failed after retries: {last_error}") from last_error


def generate_text(prompt: str, *, system_instruction: str | None = None) -> str:
    """Plain-text generation with retry/backoff.

    Raises LLMUnavailableError if the API key is missing or every retry is
    exhausted — callers are expected to catch this and fall back to a
    deterministic template.
    """
    settings = get_settings()
    client = _client()
    config = types.GenerateContentConfig(system_instruction=system_instruction) if system_instruction else None

    def _request():
        response = client.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
        return response.text or ""

    return _call_with_retry(_request)


def generate_structured(prompt: str, schema: type[T], *, system_instruction: str | None = None) -> T:
    """JSON-mode generation, validated into `schema`. Falls back to manual
    JSON parsing of `.text` if `.parsed` isn't populated."""
    settings = get_settings()
    client = _client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=schema,
    )

    def _request() -> T:
        response = client.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate(json.loads(response.text))

    return _call_with_retry(_request)
