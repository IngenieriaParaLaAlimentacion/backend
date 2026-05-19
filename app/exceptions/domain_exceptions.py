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
