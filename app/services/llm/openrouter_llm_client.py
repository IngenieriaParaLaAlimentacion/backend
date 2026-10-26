import asyncio
import base64
import json
import random
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog

from app.core.interfaces.llm_client import ILlmClient
from app.exceptions.domain_exceptions import (
    LlmClientError,
    LlmQuotaExhaustedError,
    LlmUnavailableError,
)
from app.services.llm.retry_policy import retry_after_seconds
from app.services.llm.structured_schema import structured_schema

logger = structlog.get_logger()


class _PermanentUnavailable(LlmUnavailableError):
    pass


class OpenRouterLlmClient(ILlmClient):
    """Structured text and image completions through eligible free endpoints."""

    def __init__(self, *, settings, transport=None):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1/",
            timeout=httpx.Timeout(settings.openrouter_request_timeout_seconds),
            follow_redirects=False,
            transport=transport,
        )
        self._catalog: dict[str, dict] = {}
        self._catalog_until = 0.0
        self._catalog_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Close reusable network connections."""
        if self._http.is_closed:
            return
        try:
            await self._http.aclose()
        except Exception:
            raise LlmClientError("Inference transport cleanup failed") from None

    async def _models(self) -> dict[str, dict]:
        async with self._catalog_lock:
            if time.monotonic() < self._catalog_until:
                return self._catalog
            try:
                response = await self._http.get("models", timeout=5)
                response.raise_for_status()
                data = response.json()["data"]
                if not isinstance(data, list):
                    raise ValueError("Invalid model catalogue")
                if any(
                    not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    for row in data
                ):
                    raise ValueError("Invalid model catalogue entry")
                catalog = {row["id"]: row for row in data}
                if len(catalog) != len(data):
                    raise ValueError("Duplicate model catalogue entry")
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                raise LlmUnavailableError("Model catalogue unavailable") from None
            self._catalog = catalog
            self._catalog_until = time.monotonic() + 300
            return catalog

    @staticmethod
    def _eligible(row: dict, *, image: bool) -> bool:
        try:
            if not row["id"].endswith(":free"):
                return False
            pricing = row["pricing"]
            if not isinstance(pricing, dict):
                return False
            if any(
                Decimal(str(pricing.get(key, "0"))) != 0
                for key in ("prompt", "completion", "request", "image")
            ):
                return False
            # Prompt/completion prices must be present rather than assumed free.
            if "prompt" not in pricing or "completion" not in pricing:
                return False
            parameters = set(row["supported_parameters"])
            if not {"response_format", "structured_outputs"} <= parameters:
                return False
            modalities = row["architecture"]["input_modalities"]
            return (
                isinstance(modalities, list)
                and "text" in modalities
                and (not image or "image" in modalities)
            )
        except (KeyError, TypeError, InvalidOperation, ValueError):
            return False

    @staticmethod
    def _read_response(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 429:
            raise LlmQuotaExhaustedError(
                retry_after_seconds(response.headers.get("Retry-After"))
            )
        if response.status_code in {401, 402, 403}:
            raise _PermanentUnavailable("Provider configuration unavailable")
        if response.status_code in {404, 408} or response.status_code >= 500:
            raise LlmUnavailableError("Provider unavailable")
        try:
            body = response.json()
        except ValueError:
            raise LlmClientError("Provider returned invalid response JSON") from None
        if not isinstance(body, dict):
            raise LlmClientError("Provider returned a non-object response")
        has_error = "error" in body
        error = body.get("error")
        error = error if isinstance(error, dict) else {}
        try:
            code = (
                response.status_code
                if response.status_code >= 400
                else int(error.get("code", response.status_code))
            )
        except (OverflowError, TypeError, ValueError):
            code = response.status_code
        if code == 429:
            raise LlmQuotaExhaustedError(
                retry_after_seconds(response.headers.get("Retry-After"))
            )
        if response.status_code >= 400 or has_error:
            if code in {401, 402, 403}:
                raise _PermanentUnavailable("Provider configuration unavailable")
            if code in {404, 408} or code >= 500:
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
        if not key or not configured or not providers:
            raise LlmUnavailableError("Inference is not configured")
        catalog = await self._models()
        models = [
            model
            for model in dict.fromkeys(configured)
            if self._eligible(catalog.get(model, {}), image=image is not None)
        ]
        if not models:
            raise LlmUnavailableError("No eligible free endpoint")
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
        for attempt in range(settings.openrouter_max_attempts):
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
                    "only": providers,
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
                if attempt + 1 == settings.openrouter_max_attempts:
                    raise LlmUnavailableError("Inference attempts exhausted") from None
                await asyncio.sleep(
                    random.uniform(0, settings.openrouter_retry_backoff_max_seconds)
                )
        raise LlmUnavailableError("Inference attempts exhausted")
