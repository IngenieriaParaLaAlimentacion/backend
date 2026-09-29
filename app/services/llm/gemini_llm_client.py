import json
from typing import Any

import httpx
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

# Raw transport failures below the SDK's APIError layer (connection reset,
# socket timeout) -- retried the same as a 5xx/429 response from the API.
_TRANSIENT_TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.ConnectError)


def _log_retry(retry_state: RetryCallState, *, model: str) -> None:
    """Log a Gemini call attempt that failed and will be retried."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "gemini_llm_call_retrying",
        model=model,
        attempt=retry_state.attempt_number,
        error=str(exc),
    )


class GeminiLlmClient(ILlmClient):
    """LLM completions backed by Google's Gemini API.

    Retries a transient failure against the configured model, then falls
    back to a secondary model -- when ``settings.gemini_fallback_model`` is
    set -- before giving up.

    The client holds no per-request state beyond the API key, so one
    instance is reused for the object's lifetime rather than opened fresh
    per call.
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Return whether ``exc`` is a transient Gemini failure worth retrying.

        Server errors (5xx), request timeouts (408), rate limiting (429), and
        raw transport failures (connection reset, socket timeout) are
        retried; any other client error (bad request, auth, not found) is
        not, since retrying it would just delay the same failure.
        """
        if isinstance(exc, ServerError):
            return True
        if isinstance(exc, ClientError):
            return exc.code in (408, 429)
        return isinstance(exc, _TRANSIENT_TRANSPORT_ERRORS)

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

        response = await self._generate_with_fallback(
            contents=contents, response_schema=response_schema
        )

        logger.info("gemini_llm_response", raw_text=response.text)

        if not response.text:
            raise LlmClientError("empty response from Gemini")
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise LlmClientError(f"non-JSON response: {exc}") from exc

    async def _generate_with_fallback(
        self, *, contents: list[Any], response_schema: dict[str, Any]
    ) -> types.GenerateContentResponse:
        """Call Gemini, trying each configured model in order.

        Each model gets its own retry budget (see ``_generate_with_retry``).
        Moves on to the next model only when the previous one's failure was
        retryable; a permanent failure (bad request, auth, ...) raises
        immediately instead of wasting time on a model that will fail the
        same way.

        Raises:
            LlmClientError: every configured model failed.
        """
        models = [(settings.gemini_model, settings.gemini_max_attempts)]
        if settings.gemini_fallback_model:
            models.append(
                (settings.gemini_fallback_model, settings.gemini_fallback_max_attempts)
            )

        for index, (model, max_attempts) in enumerate(models):
            logger.info("gemini_llm_call", model=model, has_image=len(contents) > 1)
            try:
                return await self._generate_with_retry(
                    model=model,
                    contents=contents,
                    response_schema=response_schema,
                    max_attempts=max_attempts,
                )
            except (APIError, *_TRANSIENT_TRANSPORT_ERRORS) as exc:
                is_last_model = index == len(models) - 1
                if is_last_model or not self._is_retryable(exc):
                    logger.warning(
                        "gemini_llm_call_failed", model=model, error=str(exc)
                    )
                    raise LlmClientError(str(exc)) from exc
                logger.warning(
                    "gemini_llm_call_switching_model",
                    failed_model=model,
                    next_model=models[index + 1][0],
                    error=str(exc),
                )
        raise AssertionError("unreachable: the loop above always returns or raises")

    async def _generate_with_retry(
        self,
        *,
        model: str,
        contents: list[Any],
        response_schema: dict[str, Any],
        max_attempts: int,
    ) -> types.GenerateContentResponse:
        """Call ``model`` once, retrying a transient failure up to ``max_attempts``.

        Raises:
            APIError: every attempt returned an API error, or the failure was
                not retryable.
            httpx.TimeoutException: every attempt hit a socket timeout.
            httpx.ConnectError: every attempt failed to connect.
        """
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential_jitter(
                initial=settings.gemini_retry_backoff_initial_seconds,
                max=settings.gemini_retry_backoff_max_seconds,
            ),
            retry=retry_if_exception(self._is_retryable),
            before_sleep=lambda retry_state: _log_retry(retry_state, model=model),
            reraise=True,
        ):
            with attempt:
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        http_options=types.HttpOptions(
                            timeout=int(settings.gemini_request_timeout_seconds * 1000)
                        ),
                    ),
                )
        return response
