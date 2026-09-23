from abc import ABC, abstractmethod
from typing import Any


class ILlmClient(ABC):
    """Port for a structured, optionally multimodal LLM completion.

    Knows nothing about receipts, catalogs, or meal plans -- callers build
    their own prompt and JSON schema and are responsible for validating the
    parsed result. This keeps every module that needs an LLM call (receipt
    extraction today, nutrir meal planning later) swappable to a different
    provider by replacing the one class that implements this port.
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
        """Return a JSON object matching ``response_schema``.

        Raises:
            LlmClientError: the provider call failed or returned content that
                does not match ``response_schema``.
        """
        ...
