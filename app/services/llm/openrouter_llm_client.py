import asyncio
import base64
import json
import random
from typing import Any

import httpx
import structlog
from fastapi import status

from app.core.interfaces.llm_client import ILlmClient
from app.exceptions.domain_exceptions import (
    LlmClientError,
    LlmQuotaExhaustedError,
    LlmUnavailableError,
)
from app.services.llm.retry_policy import retry_after_seconds
from app.services.llm.structured_schema import structured_schema

logger = structlog.get_logger()

_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_MAX_SECONDS = 2


class _PermanentUnavailable(LlmUnavailableError):
    pass


class OpenRouterLlmClient(ILlmClient):
    """Structured text and image completions through configured OpenRouter models."""

    def __init__(self, *, settings, transport=None):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1/",
            timeout=httpx.Timeout(settings.openrouter_request_timeout_seconds),
            follow_redirects=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Close reusable network connections."""
        if self._http.is_closed:
            return
        try:
            await self._http.aclose()
        except Exception:
            raise LlmClientError("Inference transport cleanup failed") from None

    @staticmethod
    def _read_response(response: httpx.Response) -> dict[str, Any]:
        code = response.status_code
        has_error = code >= status.HTTP_400_BAD_REQUEST
        body = {}
        if not has_error:
            try:
                body = response.json()
            except ValueError:
                raise LlmClientError(
                    "Provider returned invalid response JSON"
                ) from None
            if not isinstance(body, dict):
                raise LlmClientError("Provider returned a non-object response")
            has_error = "error" in body
            error = body.get("error")
            if isinstance(error, dict):
                try:
                    code = int(error.get("code", code))
                except (OverflowError, TypeError, ValueError):
                    pass
        if has_error:
            if code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise LlmQuotaExhaustedError(
                    retry_after_seconds(response.headers.get("Retry-After"))
                )
            if code in {
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_402_PAYMENT_REQUIRED,
                status.HTTP_403_FORBIDDEN,
            }:
                raise _PermanentUnavailable("Provider configuration unavailable")
            if (
                code
                in {
                    status.HTTP_404_NOT_FOUND,
                    status.HTTP_408_REQUEST_TIMEOUT,
                }
                or code >= status.HTTP_500_INTERNAL_SERVER_ERROR
            ):
                raise LlmUnavailableError("Provider unavailable")
            raise LlmClientError("Provider rejected structured completion")
        try:
            choice = body["choices"][0]
            message = choice["message"]
            if choice.get("finish_reason") != "stop" or message.get("refusal"):
                raise ValueError("Incomplete or refused completion")
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Missing completion content")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError("Completion is not an object")
            return result
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            raise LlmClientError(
                "Provider returned invalid structured content"
            ) from None

    async def complete(
        self,
        *,
        prompt: str,
        response_schema: dict[str, Any],
        image: bytes | None = None,
        image_content_type: str | None = None,
    ) -> dict[str, Any]:
        """Return one parsed JSON object within a single completion budget."""
        try:
            async with asyncio.timeout(
                self.settings.openrouter_completion_timeout_seconds
            ):
                return await self._complete(
                    prompt=prompt,
                    response_schema=response_schema,
                    image=image,
                    image_content_type=image_content_type,
                )
        except TimeoutError:
            raise LlmUnavailableError("Completion deadline exceeded") from None

    async def _complete(self, *, prompt, response_schema, image, image_content_type):
        settings = self.settings
        key = settings.openrouter_api_key
        configured = (
            settings.openrouter_receipt_models
            if image is not None
            else settings.openrouter_recipe_models
        )
        providers = settings.openrouter_allowed_providers
        if not key or not configured:
            raise LlmUnavailableError("Inference is not configured")
        models = list(dict.fromkeys(configured))
        content = [{"type": "text", "text": prompt}]
        if image is not None:
            if image_content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise LlmClientError("Unsupported completion image type")
            encoded = base64.b64encode(image).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_content_type};base64,{encoded}"},
                }
            )
        schema = structured_schema(response_schema)
        for attempt in range(_MAX_ATTEMPTS):
            model = models[min(attempt, len(models) - 1)]
            payload = {
                "model": model,
                "stream": False,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": settings.openrouter_max_output_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_completion",
                        "strict": True,
                        "schema": schema,
                    },
                },
                "provider": {
                    "allow_fallbacks": False,
                    "require_parameters": True,
                    "data_collection": "deny",
                    "max_price": {
                        "prompt": 0,
                        "completion": 0,
                        "request": 0,
                        "image": 0,
                    },
                },
            }
            if providers:
                payload["provider"]["only"] = providers
            logger.info(
                "llm.call",
                gateway="openrouter",
                model=model,
                attempt=attempt + 1,
                has_image=image is not None,
            )
            try:
                response = await self._http.post(
                    "chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                )
                return self._read_response(response)
            except (LlmQuotaExhaustedError, _PermanentUnavailable):
                raise  # Account quota/auth failures are not fixed by model fallback.
            except (httpx.TransportError, LlmUnavailableError) as exc:
                logger.warning(
                    "llm.unavailable",
                    gateway="openrouter",
                    model=model,
                    attempt=attempt + 1,
                    error_type=type(exc).__name__,
                )
                if attempt + 1 == _MAX_ATTEMPTS:
                    raise LlmUnavailableError("Inference attempts exhausted") from None
                await asyncio.sleep(random.uniform(0, _RETRY_BACKOFF_MAX_SECONDS))
        raise LlmUnavailableError("Inference attempts exhausted")
