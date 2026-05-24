from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.domain_exceptions import (
    AlreadyExistsError,
    BaseError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)


def _build_error_response(e: BaseError, request: Request, status_code: int):
    return JSONResponse(
        status_code=status_code,
        content={
            "type": f"/errors/{e.title.lower().replace(' ', '-')}",
            "title": e.title,
            "status": status_code,
            "detail": e.details,
            "instance": request.url.path,
        },
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


def register_exception_handlers(app: FastAPI):
    """Register exception handlers with the FastAPI app."""
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(AlreadyExistsError, already_exists_handler)
    app.add_exception_handler(UnauthorizedError, unauthorized_handler)
    app.add_exception_handler(ForbiddenError, forbidden_handler)
