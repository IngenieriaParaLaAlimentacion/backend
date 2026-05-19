from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.domain_exceptions import (
    BaseError,
    EstablishmentNotFoundError,
    PasswordNotFoundError,
    UnauthorizedError,
    UserAlreadyExistsError,
    UserNotFoundError,
)


def _build_error_response(e: BaseError, request: Request, status_code: int):
    """Build a standardized error response.

    Args:
        e (BaseError): The exception instance.
        request (Request): The incoming request.
        status_code (int): The HTTP status code for the response.


    Returns:
        JSONResponse: A JSON response with error details.
    """

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


async def user_already_exists_handler(request: Request, exc: UserAlreadyExistsError):
    """Handle UserAlreadyExistsError exceptions.

    Args:
        request (Request): The incoming request.
        exc (UserAlreadyExistsError): The exception instance.

    Returns:
        JSONResponse: A JSON response with error details.
    """

    return _build_error_response(exc, request, status.HTTP_409_CONFLICT)


async def user_not_found_handler(request: Request, exc: UserNotFoundError):
    """Handle UserNotFoundError exceptions.

    Args:
        request (Request): The incoming request.
        exc (UserNotFoundError): The exception instance.

    Returns:
        JSONResponse: A JSON response with error details.
    """

    return _build_error_response(exc, request, status.HTTP_404_NOT_FOUND)


async def password_not_found_handler(request: Request, exc: PasswordNotFoundError):
    """Handle PasswordNotFoundError exceptions.

    Args:
        request (Request): The incoming request.
        exc (PasswordNotFoundError): The exception instance.

    Returns:
        JSONResponse: A JSON response with error details.
    """

    return _build_error_response(exc, request, status.HTTP_404_NOT_FOUND)


async def unauthorized_handler(request: Request, exc: UnauthorizedError):
    """Handle UnauthorizedError exceptions.

    Args:
        request (Request): The incoming request.
        exc (UnauthorizedError): The exception instance.

    Returns:
        JSONResponse: A JSON response with error details.
    """

    return _build_error_response(exc, request, status.HTTP_401_UNAUTHORIZED)


async def establishment_not_found_handler(
    request: Request, exc: EstablishmentNotFoundError
):
    """Handle EstablishmentNotFoundError exceptions.

    Args:
        request (Request): The incoming request.
        exc (EstablishmentNotFoundError): The exception instance.

    Returns:
        JSONResponse: A JSON response with error details.
    """

    return _build_error_response(exc, request, status.HTTP_404_NOT_FOUND)


def register_exception_handlers(app: FastAPI):
    """Register exception handlers with the FastAPI app.

    Args:
        app (FastAPI): The FastAPI application instance.
    """
    app.add_exception_handler(UserAlreadyExistsError, user_already_exists_handler)
    app.add_exception_handler(UserNotFoundError, user_not_found_handler)
    app.add_exception_handler(PasswordNotFoundError, password_not_found_handler)
    app.add_exception_handler(UnauthorizedError, unauthorized_handler)
    app.add_exception_handler(
        EstablishmentNotFoundError, establishment_not_found_handler
    )
