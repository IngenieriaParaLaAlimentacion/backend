from abc import ABC, abstractmethod
from typing import Any


class ILlmClient(ABC):
    """Port for structured text and optional image completions.

    Receipt and recipe callers supply prompts and wire schemas. The adapter
    validates the response envelope and JSON object shape; callers retain
    authoritative domain and per-item validation.
    """

    @abstractmethod
    async def complete(
        self,
        *,
        prompt: str,
        response_schema: dict[str, Any],
        image: bytes | None = None,
        image_content_type: str | None = None,
    ) -> dict[str, Any]:
        """Return a parsed JSON object requested through response_schema.

        Raises:
            LlmQuotaExhaustedError: provider usage limit prevented completion.
            LlmUnavailableError: no eligible endpoint completed the request.
            LlmClientError: invalid, refused or incomplete structured content.
        """
        ...

    async def aclose(self) -> None:
        """Release resources owned by this client."""
        return None
