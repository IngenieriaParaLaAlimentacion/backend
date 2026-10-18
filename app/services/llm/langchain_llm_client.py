import base64
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config.settings import settings
from app.core.interfaces.llm_client import ILlmClient
from app.exceptions.domain_exceptions import LlmClientError
from app.services.llm.retry_policy import is_retryable, log_retry


def _provider_error(exc: Exception) -> Exception:
    seen = set()
    while exc.__cause__ is not None and id(exc) not in seen:
        seen.add(id(exc))
        exc = exc.__cause__
    return exc


class LangChainLlmClient(ILlmClient):
    """Structured Gemini completions through LangChain with the Gemini retry policy."""

    async def complete(
        self,
        *,
        prompt: str,
        response_schema: dict[str, Any],
        image: bytes | None = None,
        image_content_type: str | None = None,
    ) -> dict[str, Any]:
        """Return structured JSON or raise LlmClientError after bounded retries."""
        models = [(settings.gemini_model, settings.gemini_max_attempts)]
        if settings.gemini_fallback_model:
            models.append(
                (settings.gemini_fallback_model, settings.gemini_fallback_max_attempts)
            )
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image is not None:
            encoded = base64.b64encode(image).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_content_type};base64,{encoded}"},
                }
            )
        for index, (model_name, attempts) in enumerate(models):
            model = None
            try:
                model = ChatGoogleGenerativeAI(
                    model=model_name,
                    api_key=settings.gemini_api_key,
                    vertexai=False,
                    max_retries=0,
                    timeout=settings.gemini_request_timeout_seconds,
                )
                structured = model.with_structured_output(
                    response_schema, method="json_schema"
                )
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(attempts),
                    wait=wait_exponential_jitter(
                        initial=settings.gemini_retry_backoff_initial_seconds,
                        max=settings.gemini_retry_backoff_max_seconds,
                    ),
                    retry=retry_if_exception(
                        lambda exc: is_retryable(_provider_error(exc))
                    ),
                    before_sleep=lambda state: log_retry(state, model=model_name),
                    reraise=True,
                ):
                    with attempt:
                        result = await structured.ainvoke(
                            [HumanMessage(content=content)]
                        )
                        if not isinstance(result, dict):
                            raise LlmClientError("Expected a structured JSON object")
                        return result
            except Exception as exc:
                if isinstance(exc, (LlmClientError, OutputParserException)):
                    raise LlmClientError("Invalid structured model response") from exc
                if index == len(models) - 1 or not is_retryable(_provider_error(exc)):
                    raise LlmClientError("Recipe model request failed") from exc
            finally:
                if model is not None and model.client is not None:
                    await model.client.aio.aclose()
                    model.client.close()
        raise LlmClientError("No configured recipe model")
