import httpx
import structlog
from google.genai.errors import ClientError, ServerError
from tenacity import RetryCallState

logger = structlog.get_logger()

# Raw transport failures below the SDK's APIError layer (connection reset,
# socket timeout) -- retried the same as a 5xx/429 response from the API.
TRANSIENT_TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.ConnectError)


def log_retry(retry_state: RetryCallState, *, model: str) -> None:
    """Log a Gemini call attempt that failed and will be retried."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "gemini_llm_call_retrying",
        model=model,
        attempt=retry_state.attempt_number,
        error_type=type(exc).__name__,
        status_code=getattr(exc, "code", None),
    )


def is_retryable(exc: Exception) -> bool:
    """Classify transient Gemini HTTP and transport errors."""
    if isinstance(exc, ServerError):
        return True
    if isinstance(exc, ClientError):
        return exc.code in (408, 429)
    return isinstance(exc, TRANSIENT_TRANSPORT_ERRORS)
