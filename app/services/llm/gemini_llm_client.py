import json
from typing import Any

import structlog
from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.config.settings import settings
from app.core.interfaces.llm_client import ILlmClient
from app.exceptions.domain_exceptions import LlmClientError

logger = structlog.get_logger()


class GeminiLlmClient(ILlmClient):
    """LLM completions backed by Google's Gemini API.

    The client holds no per-request state beyond the API key, so one
    instance is reused for the object's lifetime rather than opened fresh
    per call.
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

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
