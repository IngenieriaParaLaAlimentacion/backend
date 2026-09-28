import json
from typing import Any

import structlog
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config.settings import settings
from app.core.interfaces.llm_client import ILlmClient
from app.exceptions.domain_exceptions import LlmClientError

logger = structlog.get_logger()

# Total attempts (first call + retries) for a transient Gemini failure.
_MAX_ATTEMPTS = 3
# Exponential backoff with jitter between attempts, capped so the worst case
# (2 retries) stays well under a mobile client's request timeout.
_BACKOFF_INITIAL_SECONDS = 1
_BACKOFF_MAX_SECONDS = 8


def _log_retry(retry_state: RetryCallState) -> None:
    """Log a Gemini call attempt that failed and will be retried."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "gemini_llm_call_retrying",
        attempt=retry_state.attempt_number,
        error=str(exc),
    )


class GeminiLlmClient(ILlmClient):
    """LLM completions backed by Google's Gemini API.

    The client holds no per-request state beyond the API key, so one
    instance is reused for the object's lifetime rather than opened fresh
    per call.
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @staticmethod
    def _is_retryable(exc: APIError) -> bool:
        """Return whether ``exc`` is a transient Gemini failure worth retrying.

        Server errors (5xx) and rate limiting (429) are retried; any other
        client error (bad request, auth, not found) is not, since retrying it
        would just delay the same failure.
        """
        if isinstance(exc, ServerError):
            return True
        return isinstance(exc, ClientError) and exc.code == 429

    async def complete(
        self,
        *,
        prompt: str,
        response_schema: dict[str, Any],
        image: bytes | None = None,
        image_content_type: str | None = None,
    ) -> dict[str, Any]:
        contents: list[Any] = [prompt]
        if image is not None:
            contents.append(
                types.Part.from_bytes(data=image, mime_type=image_content_type)
            )

        logger.info(
            "gemini_llm_call", model=settings.gemini_model, has_image=image is not None
        )
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(_MAX_ATTEMPTS),
                wait=wait_exponential_jitter(
                    initial=_BACKOFF_INITIAL_SECONDS, max=_BACKOFF_MAX_SECONDS
                ),
                retry=retry_if_exception(self._is_retryable),
                before_sleep=_log_retry,
                reraise=True,
            ):
                with attempt:
                    response = await self._client.aio.models.generate_content(
                        model=settings.gemini_model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=response_schema,
                        ),
                    )
        except APIError as exc:
            logger.warning("gemini_llm_call_failed", error=str(exc))
            raise LlmClientError(str(exc)) from exc

        logger.info("gemini_llm_response", raw_text=response.text)

        if not response.text:
            raise LlmClientError("empty response from Gemini")
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise LlmClientError(f"non-JSON response: {exc}") from exc
