from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError
from langchain_core.exceptions import OutputParserException

from app.config.settings import settings
from app.exceptions.domain_exceptions import LlmClientError
from app.services.llm.langchain_llm_client import LangChainLlmClient


def model():
    instance = MagicMock()
    instance.client.aio.aclose = AsyncMock()
    instance.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value={"ok": True}
    )
    return instance


@pytest.fixture(autouse=True)
def retry_settings(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "primary")
    monkeypatch.setattr(settings, "gemini_max_attempts", 2)
    monkeypatch.setattr(settings, "gemini_retry_backoff_initial_seconds", 0)
    monkeypatch.setattr(settings, "gemini_retry_backoff_max_seconds", 0)
    monkeypatch.setattr(settings, "gemini_fallback_model", None)


async def test_structured_langchain_output_and_cleanup():
    instance = model()
    with patch(
        "app.services.llm.langchain_llm_client.ChatGoogleGenerativeAI",
        return_value=instance,
    ) as constructor:
        result = await LangChainLlmClient().complete(
            prompt="select", response_schema={"type": "object"}
        )
    assert result == {"ok": True}
    assert constructor.call_args.kwargs["max_retries"] == 0
    instance.with_structured_output.assert_called_once_with(
        {"type": "object"}, method="json_schema"
    )
    instance.client.aio.aclose.assert_awaited_once()
    instance.client.close.assert_called_once()


async def test_transient_retry_then_fallback(monkeypatch):
    monkeypatch.setattr(settings, "gemini_fallback_model", "fallback")
    first, second = model(), model()
    first.with_structured_output.return_value.ainvoke.side_effect = ServerError(
        503, {"error": {"message": "unavailable"}}
    )
    with patch(
        "app.services.llm.langchain_llm_client.ChatGoogleGenerativeAI",
        side_effect=[first, second],
    ):
        assert await LangChainLlmClient().complete(prompt="x", response_schema={}) == {
            "ok": True
        }
    assert first.with_structured_output.return_value.ainvoke.await_count == 2
    second.with_structured_output.return_value.ainvoke.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [
        ClientError(400, {"error": {"message": "invalid"}}),
        OutputParserException("bad JSON"),
    ],
)
async def test_permanent_or_invalid_response_is_not_retried(error):
    instance = model()
    instance.with_structured_output.return_value.ainvoke.side_effect = error
    with patch(
        "app.services.llm.langchain_llm_client.ChatGoogleGenerativeAI",
        return_value=instance,
    ):
        with pytest.raises(LlmClientError):
            await LangChainLlmClient().complete(prompt="x", response_schema={})
    instance.with_structured_output.return_value.ainvoke.assert_awaited_once()
