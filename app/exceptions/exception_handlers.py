from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.domain_exceptions import BaseError
from app.utils.db import sqlstate


def _problem_response(
    request: Request,
    *,
    status_code: int,
    error_type: str,
    title: str,
    detail: str,
    extensions: dict | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    """Build the canonical RFC 7807 problem+json response.

    Extension members are merged FIRST so a stray key named ``type`` or ``status``
    can never overwrite a canonical member.
    """
    content: dict = dict(extensions or {})
    content.update(
        {
            "type": f"/errors/{error_type}",
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": request.url.path,
        }
    )
    return JSONResponse(
        status_code=status_code,
        content=content,
        media_type="application/problem+json",
        headers=headers,
    )


async def domain_error_handler(request: Request, exc: BaseError) -> JSONResponse:
    """Render any domain exception. Status and identity come from the class."""
    if exc.status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        # OTel's middleware sits outside ExceptionMiddleware, so a server-side
        # failure we resolve here would otherwise leave the span UNSET.
        trace.get_current_span().record_exception(exc)
    # RFC 7235 requires a challenge on every 401. FastAPI attached it to the
    # auto-401 it no longer raises, so we re-attach it here.
    headers = (
        {"WWW-Authenticate": "Bearer"}
        if exc.status == status.HTTP_401_UNAUTHORIZED
        else None
    )
    return _problem_response(
        request,
        status_code=exc.status,
        error_type=exc.error_type,
        title=exc.title,
        detail=exc.details,
        extensions=exc.extensions,
        headers=headers,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render Pydantic validation failures in the canonical envelope."""
    return _problem_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        error_type="validation-failed",
        title="Validation failed",
        detail="The request contains invalid or missing fields.",
    )


_HTTP_ERROR_TYPES = {
    status.HTTP_404_NOT_FOUND: ("not-found", "Not found"),
    status.HTTP_405_METHOD_NOT_ALLOWED: ("method-not-allowed", "Method not allowed"),
}


async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Render framework-raised HTTP errors (route 404/405) canonically.

    ``exc.headers`` must be forwarded or the 405 loses its ``Allow`` header.
    """
    error_type, title = _HTTP_ERROR_TYPES.get(exc.status_code, ("http-error", "Error"))
    return _problem_response(
        request,
        status_code=exc.status_code,
        error_type=error_type,
        title=title,
        detail=str(exc.detail),
        headers=getattr(exc, "headers", None),
    )


# SQLSTATE class 40: Postgres rolled the transaction back to break a deadlock
# (40P01) or because it could not serialize it (40001). Both are transient and
# leave nothing behind, unlike 40002/40003, which are not safely replayable.
_RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})


async def database_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Render a transient transaction rollback as a retryable 503.

    Postgres guarantees the losing transaction wrote nothing, so replaying the
    request verbatim is safe even on the endpoints that are not idempotent --
    which is what the ``Retry-After`` invites clients and proxies to do. The
    alternative, a bare 500, tells a caller that a retry is pointless when it is
    in fact the correct move.

    Any other database error is re-raised untouched: it reaches
    ``unhandled_error_handler`` exactly as before, so the traceback is still
    logged and the 500 stays a 500.
    """
    if sqlstate(exc) not in _RETRYABLE_SQLSTATES:
        raise exc
    # This handler sits inside the OTel middleware and answers the request, so
    # the span would otherwise close UNSET on what is still a server-side fault.
    trace.get_current_span().record_exception(exc)
    return _problem_response(
        request,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_type="concurrent-update",
        title="Concurrent update",
        detail=(
            "The request lost a race against another transaction and was rolled "
            "back without writing anything. Retry it unchanged."
        ),
        headers={"Retry-After": "1"},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: render any unhandled exception canonically.

    Starlette's ServerErrorMiddleware re-raises after this returns, so uvicorn
    still logs the traceback -- nothing is swallowed. The exception is not
    recorded on the span here: this handler runs in ServerErrorMiddleware, which
    is OUTSIDE the OTel middleware, so by now that middleware has already
    recorded the exception and ended and detached the span.
    """
    return _problem_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type="internal-error",
        title="Internal server error",
        detail="An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers with the FastAPI app."""
    app.add_exception_handler(BaseError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(DBAPIError, database_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
