"""This module defines custom domain exceptions for the application."""


class BaseError(Exception):
    """Base exception class for domain errors.

    Args:
        title (str): The title of the error.
        details (str): Detailed description of the error.
    """

    def __init__(self, title: str, details: str):
        self.title = title
        self.details = details
        super().__init__(f"{title}: {details}")


class UserNotFoundError(BaseError):
    """Exception raised when a user is not found.

    Args:
        user_id (str): The ID of the user that was not found.
    """

    def __init__(self, user_id: str):
        super().__init__("User not found", f"The user with ID {user_id} was not found.")


class UserAlreadyExistsError(BaseError):
    """Exception raised when trying to register with an existing email.

    Args:
        email (str): The email that already exists.
    """

    def __init__(self, email: str):
        super().__init__(
            "User already exists", f"A user with email {email} already exists."
        )


class PasswordNotFoundError(BaseError):
    """Exception raised when a user's password record is not found.

    Args:
        user_id (str): The ID of the user whose password was not found.
    """

    def __init__(self, user_id: str):
        super().__init__(
            "Password not found",
            f"The password record for user {user_id} was not found.",
        )


class UnauthorizedError(BaseError):
    """Exception raised when authorization fails."""

    def __init__(self):
        super().__init__(
            "Unauthorized", "Authentication credentials are missing or invalid."
        )


class ForbiddenError(BaseError):
    """Exception raised when the authenticated user lacks the required permissions."""

    def __init__(self):
        super().__init__(
            "Forbidden", "You do not have permission to perform this action."
        )


class EstablishmentNotFoundError(BaseError):
    """Exception raised when an establishment is not found.

    Args:
        establishment_id (str): The ID of the establishment that was not found.
    """

    def __init__(self, establishment_id: str):
        super().__init__(
            "Establishment not found",
            f"The establishment with id {establishment_id} was not found.",
        )


class UserEstablishmentNotFoundError(BaseError):
    """Exception raised when a user-establishment relation does not exist."""

    def __init__(self, establishment_id: str, user_id: str):
        super().__init__(
            "User establishment not found",
            f"The establishment with id {establishment_id} is not associated with the "
            f"user with id {user_id}.",
        )


class InvalidCredentialsError(BaseError):
    """Exception raised when credentials are invalid.

    Args:
        reason (str): The reason why the credentials are invalid.
    """

    def __init__(self, reason: str = "The credentials are invalid"):
        super().__init__("Invalid credentials", reason)


class PendingValidationError(BaseError):
    """Exception raised when a user attempts to log in with a pending account."""

    def __init__(self):
        super().__init__(
            "Account pending validation",
            "Wait until administrator approval.",
        )


class InvalidTokenError(BaseError):
    """Exception raised when a token is invalid, expired, or revoked.

    Args:
        reason (str): The specific reason why the token is invalid.
    """

    def __init__(self, reason: str = "The provided token is invalid or expired."):
        super().__init__("Invalid token", reason)


class EstablishmentAlreadyExistsError(BaseError):
    """Exception raised when trying to create an establishment that already exists.

    Args:
        place_id (str): The place_id of the establishment that already exists.
    """

    def __init__(self, place_id: str):
        super().__init__(
            "Establishment already exists",
            f"An establishment with place_id {place_id} already exists.",
        )
