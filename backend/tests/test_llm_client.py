from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors
from pydantic import BaseModel

from app.agents.llm_client import LLMUnavailableError, generate_structured, generate_text


class _EchoSchema(BaseModel):
    message: str


def test_generate_text_raises_without_api_key(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "")

    with pytest.raises(LLMUnavailableError):
        generate_text("hello")

    get_settings.cache_clear()


def test_generate_text_retries_on_rate_limit_then_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    from app.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.text = "hello world"

    call_count = {"n": 0}

    def _flaky_generate_content(**kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise errors.ClientError(429, {"error": {"message": "rate limited"}})
        return mock_response

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _flaky_generate_content

    with patch("app.agents.llm_client.genai.Client", return_value=mock_client), \
         patch("app.agents.llm_client.time.sleep", return_value=None):
        result = generate_text("hello")

    assert result == "hello world"
    assert call_count["n"] == 3

    get_settings.cache_clear()


def test_generate_text_does_not_retry_non_retryable_error(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    from app.config import get_settings

    get_settings.cache_clear()

    call_count = {"n": 0}

    def _permanent_failure(**kwargs):
        call_count["n"] += 1
        raise errors.ClientError(400, {"error": {"message": "invalid argument"}})

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _permanent_failure

    with patch("app.agents.llm_client.genai.Client", return_value=mock_client), \
         patch("app.agents.llm_client.time.sleep", return_value=None):
        with pytest.raises(LLMUnavailableError):
            generate_text("hello")

    assert call_count["n"] == 1  # no retry attempted for a non-retryable error

    get_settings.cache_clear()


def test_generate_text_gives_up_after_max_retries(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    from app.config import get_settings

    get_settings.cache_clear()

    call_count = {"n": 0}

    def _always_rate_limited(**kwargs):
        call_count["n"] += 1
        raise errors.ClientError(429, {"error": {"message": "rate limited"}})

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _always_rate_limited

    with patch("app.agents.llm_client.genai.Client", return_value=mock_client), \
         patch("app.agents.llm_client.time.sleep", return_value=None):
        with pytest.raises(LLMUnavailableError):
            generate_text("hello")

    from app.agents.llm_client import MAX_RETRIES
    assert call_count["n"] == MAX_RETRIES

    get_settings.cache_clear()


def test_generate_structured_uses_parsed_field(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    from app.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.parsed = _EchoSchema(message="structured ok")

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("app.agents.llm_client.genai.Client", return_value=mock_client):
        result = generate_structured("hello", _EchoSchema)

    assert isinstance(result, _EchoSchema)
    assert result.message == "structured ok"

    get_settings.cache_clear()


def test_generate_structured_falls_back_to_manual_json_parsing(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    from app.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = '{"message": "manually parsed"}'

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("app.agents.llm_client.genai.Client", return_value=mock_client):
        result = generate_structured("hello", _EchoSchema)

    assert result.message == "manually parsed"

    get_settings.cache_clear()
