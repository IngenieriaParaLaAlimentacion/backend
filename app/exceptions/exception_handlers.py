from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.domain_exceptions import (
    AlreadyExistsError,
    BadRequestError,
    BaseError,
    ConflictError,
    EmailDeliveryError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)


def _build_error_response(e: BaseError, request: Request, status_code: int):
    content = {
        "type": f"/errors/{e.title.lower().replace(' ', '-')}",
        "title": e.title,
        "status": status_code,
        "detail": e.details,
        "instance": request.url.path,
    }
    content.update(getattr(e, "extensions", {}) or {})
    return JSONResponse(
        status_code=status_code,
        content=content,
        media_type="application/problem+json",
    )


async def not_found_handler(request: Request, exc: NotFoundError):
    return _build_error_response(exc, request, status.HTTP_404_NOT_FOUND)


async def already_exists_handler(request: Request, exc: AlreadyExistsError):
    return _build_error_response(exc, request, status.HTTP_409_CONFLICT)


async def unauthorized_handler(request: Request, exc: UnauthorizedError):
    return _build_error_response(exc, request, status.HTTP_401_UNAUTHORIZED)


async def forbidden_handler(request: Request, exc: ForbiddenError):
    return _build_error_response(exc, request, status.HTTP_403_FORBIDDEN)


async def bad_request_handler(request: Request, exc: BadRequestError):
    return _build_error_response(exc, request, status.HTTP_400_BAD_REQUEST)


async def conflict_handler(request: Request, exc: ConflictError):
    return _build_error_response(exc, request, status.HTTP_409_CONFLICT)
async def email_delivery_handler(request: Request, exc: EmailDeliveryError):
    return _build_error_response(exc, request, status.HTTP_502_BAD_GATEWAY)


def register_exception_handlers(app: FastAPI):
    """Register exception handlers with the FastAPI app."""
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(AlreadyExistsError, already_exists_handler)
    app.add_exception_handler(UnauthorizedError, unauthorized_handler)
    app.add_exception_handler(ForbiddenError, forbidden_handler)
    app.add_exception_handler(BadRequestError, bad_request_handler)
    app.add_exception_handler(ConflictError, conflict_handler)
    app.add_exception_handler(EmailDeliveryError, email_delivery_handler)
