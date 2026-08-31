from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.domain_exceptions import BaseError


def _problem_response(
    request: Request,
    *,
    status_code: int,
    error_type: str,
    title: str,
    detail: str,
    extensions: dict | None = None,
    errors: list[dict] | None = None,
    reason: str | None = None,
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
    if reason:
        content["reason"] = reason
    if errors:
        content["errors"] = errors
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
        reason=exc.reason,
        headers=headers,
    )


def _field_errors(exc: RequestValidationError) -> list[dict]:
    """Flatten Pydantic errors into RFC 9457 field-level members.

    Only ``type``/``loc``/``msg`` are read. ``ctx`` is dropped because it holds a
    live ``ValueError`` for every custom validator in this codebase and is not
    JSON-serializable; ``input`` is dropped because it echoes the submitted value
    back to the client (on ``POST /auth/login`` that is the password).
    """
    errors = []
    for error in exc.errors():
        pointer = "/" + "/".join(str(part) for part in error["loc"])
        errors.append(
            {
                "pointer": pointer,
                "detail": error["msg"],
                "code": error["type"],
            }
        )
    return errors


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render Pydantic validation failures in the canonical envelope."""
    return _problem_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_type="validation-failed",
        title="Validation failed",
        detail="The request contains invalid or missing fields.",
        errors=_field_errors(exc),
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
    app.add_exception_handler(Exception, unhandled_error_handler)
