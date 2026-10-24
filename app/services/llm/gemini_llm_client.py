import json
from typing import Any

import httpx
import structlog
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config.settings import settings
from app.core.interfaces.llm_client import ILlmClient
from app.exceptions.domain_exceptions import LlmClientError
from app.services.llm.retry_policy import (
    TRANSIENT_TRANSPORT_ERRORS as _TRANSIENT_TRANSPORT_ERRORS,
)
from app.services.llm.retry_policy import (
    is_retryable,
)
from app.services.llm.retry_policy import (
    log_retry as _log_retry,
)

logger = structlog.get_logger()


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
        if not settings.gemini_api_key:
            raise LlmClientError("Gemini API key is not configured")
        self._http_client = httpx.AsyncClient()
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                httpx_async_client=self._http_client,
                # Tenacity owns retries; avoid an independent SDK retry budget.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def aclose(self) -> None:
        """Release SDK and supplied HTTP clients at application shutdown."""
        try:
            await self._client.aio.aclose()
        finally:
            try:
                self._client.close()
            finally:
                await self._http_client.aclose()

    _is_retryable = staticmethod(is_retryable)

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

        usage = getattr(response, "usage_metadata", None)
        logger.info(
            "gemini_llm_response",
            model_version=getattr(response, "model_version", None),
            response_chars=len(response.text or ""),
            total_tokens=getattr(usage, "total_token_count", None),
        )

        if not response.text:
            raise LlmClientError("empty response from Gemini")
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise LlmClientError("Gemini returned invalid JSON") from exc

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
                        "gemini_llm_call_failed",
                        model=model,
                        error_type=type(exc).__name__,
                        status_code=getattr(exc, "code", None),
                    )
                    raise LlmClientError("Gemini provider request failed") from exc
                logger.warning(
                    "gemini_llm_call_switching_model",
                    failed_model=model,
                    next_model=models[index + 1][0],
                    error_type=type(exc).__name__,
                    status_code=getattr(exc, "code", None),
                )

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
                        max_output_tokens=settings.gemini_max_output_tokens,
                        temperature=settings.gemini_temperature,
                        seed=settings.gemini_seed,
                        thinking_config=types.ThinkingConfig(
                            thinking_level=settings.gemini_thinking_level
                        )
                        if model.rsplit("/", 1)[-1].startswith("gemini-3")
                        else None,
                        # Callers provide Pydantic JSON Schema, not the legacy
                        # Google Schema dialect. Preserve refs and nested schemas.
                        response_json_schema=response_schema,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        http_options=types.HttpOptions(
                            timeout=int(settings.gemini_request_timeout_seconds * 1000)
                        ),
                    ),
                )
        return response
