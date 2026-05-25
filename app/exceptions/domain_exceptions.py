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


class NotFoundError(BaseError):
    """Base exception for resources that cannot be found."""


class AlreadyExistsError(BaseError):
    """Base exception for resources that already exist."""


class BadRequestError(BaseError):
    """Base exception for invalid client requests (HTTP 400)."""


class UserNotFoundError(NotFoundError):
    """Exception raised when a user is not found.

    Args:
        user_id (str): The ID of the user that was not found.
    """

    def __init__(self, user_id: str):
        super().__init__("User not found", f"The user with ID {user_id} was not found.")


class UserAlreadyExistsError(AlreadyExistsError):
    """Exception raised when trying to register with an existing email.

    Args:
        email (str): The email that already exists.
    """

    def __init__(self, email: str):
        super().__init__(
            "User already exists", f"A user with email {email} already exists."
        )


class PasswordNotFoundError(NotFoundError):
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

    def __init__(
        self,
        title: str = "Unauthorized",
        details: str = "Authentication credentials are missing or invalid.",
    ):
        super().__init__(title, details)


class ForbiddenError(BaseError):
    """Exception raised when the authenticated user lacks the required permissions."""

    def __init__(
        self,
        title: str = "Forbidden",
        details: str = "You do not have permission to perform this action.",
    ):
        super().__init__(title, details)


class EstablishmentNotFoundError(NotFoundError):
    """Exception raised when an establishment is not found.

    Args:
        establishment_id (str): The ID of the establishment that was not found.
    """

    def __init__(self, establishment_id: str):
        super().__init__(
            "Establishment not found",
            f"The establishment with id {establishment_id} was not found.",
        )


class UserEstablishmentNotFoundError(NotFoundError):
    """Exception raised when a user-establishment relation does not exist."""

    def __init__(self, establishment_id: str, user_id: str):
        super().__init__(
            "User establishment not found",
            f"The establishment with id {establishment_id} is not associated with the "
            f"user with id {user_id}.",
        )


class SubjectAlreadyExistsError(AlreadyExistsError):
    """Exception raised when trying to register a subject with an existing DNI.

    Args:
        dni (int): The DNI that already exists.
    """

    def __init__(self, dni: int):
        super().__init__(
            "Subject already exists",
            f"A subject with DNI {dni} already exists.",
        )


class SubjectNotFoundError(NotFoundError):
    """Exception raised when a subject cannot be found.

    Args:
        subject_id: The UUID that was looked up.
    """

    def __init__(self, subject_id: str):
        super().__init__(
            "Subject not found",
            f"No subject with id {subject_id} exists.",
        )


class UniqueConstraintError(Exception):
    """Raised by a repository when a unique constraint is violated.

    Callers (services) are responsible for translating this into the
    appropriate domain exception.
    """

    def __init__(self, field: str, value: object) -> None:
        self.field = field
        self.value = value
        super().__init__(f"Unique constraint violated: {field}={value}")


class EmptyUpdateRequestError(BadRequestError):
    """Exception raised when an update has no attributes to be updated."""

    def __init__(self):
        super().__init__(
            "No fields to update",
            "At least one field must be provided.",
        )


class InvalidCredentialsError(UnauthorizedError):
    """Exception raised when credentials are invalid.

    Args:
        reason (str): The reason why the credentials are invalid.
    """

    def __init__(self, reason: str = "The credentials are invalid"):
        super().__init__("Invalid credentials", reason)


class PendingValidationError(ForbiddenError):
    """Exception raised when a user attempts to log in with a pending account."""

    def __init__(self):
        super().__init__(
            "Account pending validation",
            "Wait until administrator approval.",
        )


class InvalidTokenError(UnauthorizedError):
    """Exception raised when a token is invalid, expired, or revoked.

    Args:
        reason (str): The specific reason why the token is invalid.
    """

    def __init__(self, reason: str = "The provided token is invalid or expired."):
        super().__init__("Invalid token", reason)
