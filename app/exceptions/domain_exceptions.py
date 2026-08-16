"""This module defines custom domain exceptions for the application."""


class BaseError(Exception):
    """Base exception class for domain errors.

    Args:
        title (str): The title of the error.
        details (str): Detailed description of the error.
        extensions (dict | None): Optional RFC 7807 extension members merged into
            the ``problem+json`` response body.
    """

    def __init__(self, title: str, details: str, extensions: dict | None = None):
        self.title = title
        self.details = details
        self.extensions = extensions or {}
        super().__init__(f"{title}: {details}")


class NotFoundError(BaseError):
    """Base exception for resources that cannot be found."""


class AlreadyExistsError(BaseError):
    """Base exception for resources that already exist."""


class BadRequestError(BaseError):
    """Base exception for invalid client requests (HTTP 400)."""


class ConflictError(BaseError):
    """Base exception for state conflicts that are not simple duplicates (HTTP 409).

    Distinct from ``AlreadyExistsError`` (also 409) so the RFC 7807 ``type``/``title``
    can convey a stateful conflict (e.g. a locked resource) rather than a duplicate.
    """


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


class EstablishmentRequestNotFoundError(NotFoundError):
    """Exception raised when an establishment request does not exist.

    Args:
        request_id (str): The ID of the establishment request that was
            not found.
    """

    def __init__(self, request_id: str):
        super().__init__(
            "Establishment request not found",
            f"The establishment request with id {request_id} was not found.",
        )


class SubjectAlreadyExistsError(AlreadyExistsError):
    """Exception raised when trying to register a subject with an existing DNI.

    Args:
        dni (int): The DNI that already exists.
        canonical (dict | None): The canonical subject already stored under this
            DNI, attached as the ``canonical_subject`` extension so the client can
            remap its local references.
    """

    def __init__(self, dni: int, canonical: dict | None = None):
        super().__init__(
            "Subject already exists",
            f"A subject with DNI {dni} already exists.",
            extensions={"canonical_subject": canonical} if canonical else None,
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


class EmailDeliveryError(BaseError):
    """Raised when an outbound email cannot be delivered to the SMTP server.

    The account/token has already been persisted at this point, so the caller
    should be directed to the resend-invite flow rather than retrying creation.
    """

    def __init__(
        self,
        details: str = (
            "The account was created but the invitation email could not be "
            "delivered. Use the resend-invite endpoint to try again."
        ),
    ):
        super().__init__("Email delivery failed", details)


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


class InvalidListingFilterError(BadRequestError):
    """Exception raised when listing filter parameters are inconsistent."""

    def __init__(self, detail: str):
        super().__init__("Invalid filter", detail)


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


class EstablishmentAlreadyExistsError(AlreadyExistsError):
    """Raised when an establishment with the given place_id already exists."""

    def __init__(self, place_id: str):
        super().__init__(
            "Establishment already exists",
            f"An establishment with place_id {place_id} already exists.",
        )


class EstablishmentRequestAlreadyReviewedError(ConflictError):
    """Raised when approving/rejecting a request that is no longer pending."""

    def __init__(self, request_id: str):
        super().__init__(
            "Establishment request already reviewed",
            f"The establishment request with id {request_id} has already "
            "been resolved and can no longer be approved or rejected.",
        )


class SurveyNotFoundError(NotFoundError):
    """Exception raised when a survey cannot be found.

    Args:
        survey_id (str): The ID that was looked up.
    """

    def __init__(self, survey_id: str):
        super().__init__(
            "Survey not found",
            f"No survey with id {survey_id} exists.",
        )


class SurveyAlreadyExistsError(AlreadyExistsError):
    """Exception raised when a survey name collides with an existing one.

    Args:
        name (str): The survey name that already exists.
    """

    def __init__(self, name: str):
        super().__init__(
            "Survey already exists",
            f"A survey named '{name}' already exists.",
        )


class SurveyLockedError(ConflictError):
    """Exception raised when a survey can no longer be modified.

    Gates structural edits — and changes to ``response_target`` — once a survey
    has recorded at least one response.
    """

    def __init__(
        self,
        detail: str = (
            "This survey has recorded responses and can no longer be modified."
        ),
    ):
        super().__init__("Survey locked", detail)


class InvalidSurveyStructureError(BadRequestError):
    """Exception raised when a survey's questions or options are inconsistent."""

    def __init__(self, detail: str):
        super().__init__("Invalid survey structure", detail)


class InvalidSurveyPayloadError(BadRequestError):
    """Exception raised when a reconcile payload references ids outside the survey."""

    def __init__(self, detail: str):
        super().__init__("Invalid survey payload", detail)


class SurveyResponseNotFoundError(NotFoundError):
    """Exception raised when a survey response cannot be found.

    Args:
        response_id (str): The ID that was looked up.
    """

    def __init__(self, response_id: str):
        super().__init__(
            "Survey response not found",
            f"No survey response with id {response_id} exists.",
        )


class InvalidSurveyResponseError(BadRequestError):
    """Exception raised when submitted answers fail validation, or the payload
    names an entity that does not match the survey's response target."""

    def __init__(self, detail: str):
        super().__init__("Invalid survey response", detail)


class SurveyResponseAlreadyExistsError(AlreadyExistsError):
    """Exception raised when a survey's target has already been answered.

    Args:
        existing (dict): JSON-primitive description of the response already
            recorded, attached as the ``existing_response`` extension.
    """

    def __init__(self, existing: dict):
        super().__init__(
            "Survey response already exists",
            "This survey has already been answered for that target.",
            extensions={"existing_response": existing},
        )
