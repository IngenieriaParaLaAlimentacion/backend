"""This module defines custom domain exceptions for the application."""

import re
from typing import ClassVar

from fastapi import status

# Every concrete domain exception registers its slug here at import time. The
# registry is what makes `error_type` a contract rather than a convention: a
# duplicate or malformed slug fails at class-definition time, which means at app
# boot and at test collection.
ERROR_REGISTRY: dict[str, type["BaseError"]] = {}

_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*")


class BaseError(Exception):
    """Base exception class for domain errors.

    Concrete subclasses must declare ``error_type`` in their own class body. It is
    the stable, machine-readable identity clients branch on, and it is deliberately
    NOT derived from ``title`` -- prose may be reworded freely without changing the
    contract.

    ``status`` may be inherited from an abstract base that declares a family
    default (e.g. every ``NotFoundError`` is a 404); override it on the subclass
    when the family default is wrong.

    Args:
        title (str): Short human-readable summary. Free prose, not a contract.
        details (str): Explanation of this specific occurrence. Free prose.
        extensions (dict | None): Optional RFC 7807 extension members merged into
            the ``problem+json`` body. Values must be JSON-primitive: the handler
            passes them straight to ``JSONResponse``, which cannot encode a raw
            ``UUID`` or ``datetime``.
    """

    error_type: ClassVar[str]
    status: ClassVar[int]

    def __init_subclass__(cls, *, abstract: bool = False, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if abstract:
            return

        if "error_type" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must declare `error_type` in its own class body. "
                "Inheriting a parent's identity would make two distinct errors "
                "indistinguishable to clients."
            )
        if not isinstance(cls.error_type, str) or not _SLUG.fullmatch(cls.error_type):
            raise TypeError(
                f"{cls.__name__}.error_type is malformed: {cls.error_type!r}. "
                "Expected lowercase kebab-case segments, optionally namespaced "
                "with '/', e.g. 'survey-locked'."
            )
        if not isinstance(getattr(cls, "status", None), int):
            raise TypeError(
                f"{cls.__name__} must declare `status` (or inherit one from an "
                "abstract base)."
            )
        if cls.error_type in ERROR_REGISTRY:
            raise TypeError(
                f"Duplicate error_type {cls.error_type!r}: {cls.__name__} "
                f"collides with {ERROR_REGISTRY[cls.error_type].__name__}."
            )
        ERROR_REGISTRY[cls.error_type] = cls

    def __init__(
        self,
        title: str,
        details: str,
        extensions: dict | None = None,
    ):
        self.title = title
        self.details = details
        self.extensions = extensions or {}
        super().__init__(f"{title}: {details}")


class NotFoundError(BaseError, abstract=True):
    """Base exception for resources that cannot be found."""

    status = status.HTTP_404_NOT_FOUND


class AlreadyExistsError(BaseError, abstract=True):
    """Base exception for resources that already exist."""

    status = status.HTTP_409_CONFLICT


class BadRequestError(BaseError, abstract=True):
    """Base exception for invalid client requests (HTTP 400)."""

    status = status.HTTP_400_BAD_REQUEST


class ConflictError(BaseError, abstract=True):
    """Base exception for state conflicts that are not simple duplicates (HTTP 409).

    Distinct from ``AlreadyExistsError`` (also 409) so the RFC 7807 ``type``/``title``
    can convey a stateful conflict (e.g. a locked resource) rather than a duplicate.
    """

    status = status.HTTP_409_CONFLICT


class UserNotFoundError(NotFoundError):
    """Exception raised when a user is not found.

    Args:
        user_id (str): The ID of the user that was not found.
    """

    error_type = "user-not-found"

    def __init__(self, user_id: str):
        super().__init__("User not found", f"The user with ID {user_id} was not found.")


class UserAlreadyExistsError(AlreadyExistsError):
    """Exception raised when trying to register with an existing email.

    Args:
        email (str): The email that already exists.
    """

    error_type = "user-already-exists"

    def __init__(self, email: str):
        super().__init__(
            "User already exists", f"A user with email {email} already exists."
        )


class PasswordNotFoundError(NotFoundError):
    """Exception raised when a user's password record is not found.

    Args:
        user_id (str): The ID of the user whose password was not found.
    """

    error_type = "password-not-found"

    def __init__(self, user_id: str):
        super().__init__(
            "Password not found",
            f"The password record for user {user_id} was not found.",
        )


class UnauthorizedError(BaseError):
    """Exception raised when authorization fails."""

    error_type = "unauthorized"
    status = status.HTTP_401_UNAUTHORIZED

    def __init__(
        self,
        title: str = "Unauthorized",
        details: str = "Authentication credentials are missing or invalid.",
        extensions: dict | None = None,
    ):
        super().__init__(title, details, extensions)


class NotificationConfigurationError(BaseError):
    """Raised when scheduled notifications are not fully configured."""

    error_type = "notification-configuration-invalid"
    status = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self):
        super().__init__(
            "Notification configuration invalid",
            "Stale-establishment notifications are not fully configured.",
        )


class ForbiddenError(BaseError, abstract=True):
    """Base exception for a request the caller is not permitted to make.

    Abstract on purpose: a 403 that says only "forbidden" gives the client no way
    to tell "your role can never do this" from "this resource is not yours".
    Raise one of the concrete subclasses.
    """

    status = status.HTTP_403_FORBIDDEN


class RoleNotAllowedError(ForbiddenError):
    """Raised when the actor's role is not permitted to perform the operation."""

    error_type = "role-not-allowed"

    def __init__(
        self,
        details: str = "Your role is not allowed to perform this action.",
    ):
        super().__init__("Role not allowed", details)


class EstablishmentAccessDeniedError(ForbiddenError):
    """Raised when a field worker acts on an establishment they have no
    approved relation with."""

    error_type = "establishment-access-denied"

    def __init__(
        self,
        details: str = ("You do not have approved access to this establishment."),
    ):
        super().__init__("Establishment access denied", details)


class NotResourceOwnerError(ForbiddenError):
    """Raised when a non-admin acts on a resource somebody else created."""

    error_type = "not-resource-owner"

    def __init__(
        self,
        details: str = "Only the author of this resource, or an admin, can modify it.",
    ):
        super().__init__("Not the resource owner", details)


class SurveyNotAvailableError(ForbiddenError):
    """Raised when a field worker reaches a survey that is not currently active."""

    error_type = "survey-not-available"

    def __init__(
        self,
        details: str = "This survey is not currently available.",
    ):
        super().__init__("Survey not available", details)


class EstablishmentNotFoundError(NotFoundError):
    """Exception raised when an establishment is not found.

    Args:
        establishment_id (str): The ID of the establishment that was not found.
    """

    error_type = "establishment-not-found"

    def __init__(self, establishment_id: str):
        super().__init__(
            "Establishment not found",
            f"The establishment with id {establishment_id} was not found.",
        )


class UserEstablishmentNotFoundError(NotFoundError):
    """Exception raised when a user-establishment relation does not exist."""

    error_type = "user-establishment-not-found"

    def __init__(self, establishment_id: str, user_id: str):
        super().__init__(
            "User establishment not found",
            f"The establishment with id {establishment_id} is not associated with the "
            f"user with id {user_id}.",
        )


class UserEstablishmentNotApprovedError(ConflictError):
    """Raised when revoking access to an establishment that isn't currently
    approved for the given user.

    Args:
        establishment_id (str): The establishment whose relation is not approved.
        user_id (str): The user the relation belongs to.
        relation_status (str | None): The state the relation is actually in
            (pending/rejected/revoked), attached as the ``relation_status``
            extension -- the three collapse into one error otherwise.
    """

    error_type = "user-establishment-not-approved"

    def __init__(
        self,
        establishment_id: str,
        user_id: str,
        relation_status: str | None = None,
    ):
        super().__init__(
            "User establishment not approved",
            f"The establishment with id {establishment_id} is not currently "
            f"approved for the user with id {user_id}.",
            extensions=(
                {"relation_status": relation_status} if relation_status else None
            ),
        )


class UserEstablishmentNotWithdrawableError(ConflictError):
    """Raised when a user tries to withdraw their own access to an
    establishment whose relation is not currently approved or pending.

    Args:
        establishment_id (str): The establishment whose relation cannot be
            withdrawn.
        user_id (str): The user the relation belongs to.
        relation_status (str): The state the relation is actually in
            (rejected/revoked), attached as the ``relation_status`` extension.
    """

    error_type = "user-establishment-not-withdrawable"

    def __init__(self, establishment_id: str, user_id: str, relation_status: str):
        super().__init__(
            "User establishment not withdrawable",
            f"The establishment with id {establishment_id} is not currently "
            f"approved or pending for the user with id {user_id}, so its "
            "access cannot be withdrawn.",
            extensions={"relation_status": relation_status},
        )


class EstablishmentRequestNotFoundError(NotFoundError):
    """Exception raised when an establishment request does not exist.

    Args:
        request_id (str): The ID of the establishment request that was
            not found.
    """

    error_type = "establishment-request-not-found"

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

    error_type = "subject-already-exists"

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

    error_type = "subject-not-found"

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

    error_type = "email-delivery-failed"
    status = status.HTTP_502_BAD_GATEWAY

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

    error_type = "no-fields-to-update"

    def __init__(self):
        super().__init__(
            "No fields to update",
            "At least one field must be provided.",
        )


class InvalidListingFilterError(BadRequestError, abstract=True):
    """Base exception for inconsistent or inapplicable listing filters."""


class InvalidDateRangeError(InvalidListingFilterError):
    """Raised when a date-range filter starts after it ends."""

    error_type = "invalid-date-range"

    def __init__(self, detail: str):
        super().__init__("Invalid date range", detail)


class InvalidAgeRangeError(InvalidListingFilterError):
    """Raised when an age-range filter has a minimum above its maximum."""

    error_type = "invalid-age-range"

    def __init__(self, detail: str):
        super().__init__("Invalid age range", detail)


class InvalidNumberRangeError(InvalidListingFilterError):
    """Raised when a response-number-range filter starts above where it ends."""

    error_type = "invalid-response-number-range"

    def __init__(self, detail: str):
        super().__init__("Invalid response number range", detail)


class FilterNotApplicableError(InvalidListingFilterError):
    """Raised when a filter resolves through a target the resource does not carry."""

    error_type = "filter-not-applicable"

    def __init__(self, detail: str):
        super().__init__("Filter not applicable", detail)


class UserNotFieldWorkerError(BadRequestError):
    """Raised when an operation requires the target user to be a field worker."""

    error_type = "user-is-not-a-field-worker"

    def __init__(self, detail: str):
        super().__init__("User is not a field worker", detail)


class InvalidUserRoleError(BadRequestError):
    """Raised when the target user's role is not valid for the operation."""

    error_type = "invalid-user-role"

    def __init__(self):
        super().__init__(
            "Invalid user role",
            "Only backoffice users (admin, analyst) receive invitations.",
        )


class UserNotActiveError(BadRequestError):
    """Raised when an operation requires the target user to be active."""

    error_type = "user-is-not-active"

    def __init__(self, detail: str):
        super().__init__("User is not active", detail)


class FieldWorkerNotPendingError(BadRequestError):
    """Raised when a field worker is not awaiting validation."""

    error_type = "field-worker-is-not-pending"

    def __init__(self, detail: str):
        super().__init__("Field worker is not pending", detail)


class UserNotPendingError(BadRequestError):
    """Raised when a user has no pending invitation."""

    error_type = "user-is-not-pending"

    def __init__(self, detail: str):
        super().__init__("User is not pending", detail)


class MissingTokenError(UnauthorizedError):
    """Raised when a protected endpoint receives no bearer token at all."""

    error_type = "auth/missing-token"

    def __init__(self):
        super().__init__(
            "Authentication required",
            "A bearer token is required to access this resource.",
        )


class UnmappedExportLabelError(BadRequestError):
    """Exception raised when a CSV export hits an enum value with no label.

    The export is aborted rather than completed with a blank cell: a silently
    missing "Femenino" or "Obesidad" is a data defect nobody would notice in a
    downloaded file. The offending map and value are named in the response and
    logged, so the gap is identifiable without reproducing the request.
    """

    error_type = "export/unmapped-label"

    def __init__(self, label_map: str, value: object):
        super().__init__(
            "Unmapped export label",
            f"No label defined in {label_map} for value {value!r}. "
            "The export was aborted rather than emitting a blank cell.",
            extensions={"label_map": label_map, "value": str(value)},
        )


class InvalidCredentialsError(UnauthorizedError):
    """Exception raised when credentials are invalid.

    Args:
        details (str): Explanation of why the credentials are invalid.
    """

    error_type = "invalid-credentials"

    def __init__(self, details: str = "The credentials are invalid"):
        super().__init__("Invalid credentials", details)


class PendingValidationError(ForbiddenError):
    """Exception raised when a user attempts to log in with a pending account."""

    error_type = "account-pending-validation"

    def __init__(self):
        super().__init__(
            "Account pending validation",
            "Wait until administrator approval.",
        )


class InvalidTokenError(UnauthorizedError, abstract=True):
    """Base exception for a token that is invalid, expired, or revoked.

    Abstract on purpose: the client recovery differs per token kind (re-login,
    request a new recovery email, request a new verification email), so the
    concrete subclass is what a client branches on.
    """


class InvalidRefreshTokenError(InvalidTokenError):
    """Raised when a refresh token is unknown, expired or already revoked."""

    error_type = "auth/invalid-refresh-token"

    def __init__(self, details: str = "Refresh token is invalid or expired."):
        super().__init__("Invalid refresh token", details)


class InvalidRecoveryTokenError(InvalidTokenError):
    """Raised when a password recovery token is unusable."""

    error_type = "auth/invalid-recovery-token"

    def __init__(self, details: str = "Password recovery token is invalid or expired."):
        super().__init__("Invalid recovery token", details)


class InvalidVerificationTokenError(InvalidTokenError):
    """Raised when an email verification token is unusable."""

    error_type = "auth/invalid-verification-token"

    def __init__(
        self, details: str = "Email verification token is invalid or expired."
    ):
        super().__init__("Invalid verification token", details)


class RecoveryTokenUsedError(InvalidTokenError):
    """Raised when a password recovery token has already been consumed.

    Requesting a new recovery link marks the previous one used, so this also
    covers "you followed an older link".
    """

    error_type = "auth/recovery-token-used"

    def __init__(self):
        super().__init__(
            "Recovery token already used",
            "This password recovery link has already been used, or a newer one "
            "was requested. Request a new link.",
        )


class RecoveryTokenExpiredError(InvalidTokenError):
    """Raised when a password recovery token is past its expiry."""

    error_type = "auth/recovery-token-expired"

    def __init__(self):
        super().__init__(
            "Recovery token expired",
            "This password recovery link has expired. Request a new one.",
        )


class VerificationTokenUsedError(InvalidTokenError):
    """Raised when an email verification token has already been consumed.

    Requesting a new verification email marks the previous token used, so this
    also covers "you followed an older link".
    """

    error_type = "auth/verification-token-used"

    def __init__(self):
        super().__init__(
            "Verification token already used",
            "This verification link has already been used, or a newer one was "
            "requested. Request a new link.",
        )


class VerificationTokenExpiredError(InvalidTokenError):
    """Raised when an email verification token is past its expiry."""

    error_type = "auth/verification-token-expired"

    def __init__(self):
        super().__init__(
            "Verification token expired",
            "This verification link has expired. Request a new one.",
        )


class InvitePendingError(ConflictError):
    """Raised when inviting an address that already has a pending invitation.

    Carries the ``user_id`` extension because the client needs it to call the
    resend-invite endpoint and has no other way to obtain it.

    Args:
        user_id (str): The id of the already-invited, still-pending user.
    """

    error_type = "admin/invite-already-pending"

    def __init__(self, user_id: str):
        super().__init__(
            "Invitation already pending",
            "This address has already been invited and has not completed "
            "onboarding yet. Use the resend-invite endpoint.",
            extensions={"user_id": user_id},
        )


class EstablishmentAlreadyExistsError(AlreadyExistsError):
    """Raised when an establishment with the given place_id already exists."""

    error_type = "establishment-already-exists"

    def __init__(self, place_id: str):
        super().__init__(
            "Establishment already exists",
            f"An establishment with place_id {place_id} already exists.",
        )


class EstablishmentRequestAlreadyReviewedError(ConflictError):
    """Raised when approving/rejecting a request that is no longer pending.

    Args:
        request_id (str): The request that is already resolved.
        current_status (str | None): The terminal state it is in, attached as
            the ``current_status`` extension so the client can say which.
    """

    error_type = "establishment-request-already-reviewed"

    def __init__(self, request_id: str, current_status: str | None = None):
        super().__init__(
            "Establishment request already reviewed",
            f"The establishment request with id {request_id} has already "
            "been resolved and can no longer be approved or rejected.",
            extensions=({"current_status": current_status} if current_status else None),
        )


class SurveyNotFoundError(NotFoundError):
    """Exception raised when a survey cannot be found.

    Args:
        survey_id (str): The ID that was looked up.
    """

    error_type = "survey-not-found"

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

    error_type = "survey-already-exists"

    def __init__(self, name: str):
        super().__init__(
            "Survey already exists",
            f"A survey named '{name}' already exists.",
        )


class SurveyLockedError(ConflictError):
    """Exception raised when an edit to a survey with recorded responses would
    invalidate them.

    Once a survey has recorded at least one response, most structural edits and
    any change to ``response_target`` are rejected -- except adding a new
    optional question, which is still allowed. One identity and one client
    recovery ("that edit isn't allowed anymore") for every trigger, so the
    specific trigger is carried by ``detail`` rather than by six near-identical
    classes.

    Args:
        detail (str): Human-readable explanation of this occurrence.
    """

    error_type = "survey-locked"

    def __init__(self, detail: str):
        super().__init__("Survey locked", detail)


class InvalidSurveyStructureError(BadRequestError):
    """Exception raised when a survey's questions or options are inconsistent."""

    error_type = "invalid-survey-structure"

    def __init__(self, detail: str):
        super().__init__("Invalid survey structure", detail)


class InvalidSurveyPayloadError(BadRequestError):
    """Exception raised when a reconcile payload references ids outside the survey."""

    error_type = "invalid-survey-payload"

    def __init__(self, detail: str):
        super().__init__("Invalid survey payload", detail)


class SurveyResponseNotFoundError(NotFoundError):
    """Exception raised when a survey response cannot be found.

    Args:
        response_id (str): The ID that was looked up.
    """

    error_type = "survey-response-not-found"

    def __init__(self, response_id: str):
        super().__init__(
            "Survey response not found",
            f"No survey response with id {response_id} exists.",
        )


class InvalidSurveyResponseError(BadRequestError):
    """Exception raised when submitted answers fail validation, or the payload
    names an entity that does not match the survey's response target.

    Args:
        detail (str): Human-readable explanation of this occurrence.
    """

    error_type = "invalid-survey-response"

    def __init__(self, detail: str):
        super().__init__("Invalid survey response", detail)


class SurveyResponseAlreadyExistsError(AlreadyExistsError):
    """Exception raised when a survey's target has already been answered.

    Args:
        existing (dict | None): JSON-primitive description of the response
            already recorded, attached as the ``existing_response`` extension.
            Absent on the DB-race path, where the conflicting row is not loaded.
    """

    error_type = "survey-response-already-exists"

    def __init__(self, existing: dict | None = None):
        extensions: dict = {}
        if existing:
            extensions["existing_response"] = existing
        super().__init__(
            "Survey response already exists",
            "This survey has already been answered for that target.",
            extensions=extensions or None,
        )


class FoodNotFoundError(NotFoundError):
    """Exception raised when a food cannot be found.

    Args:
        food_id (str): The ID that was looked up.
    """

    error_type = "food-not-found"

    def __init__(self, food_id: str):
        super().__init__(
            "Food not found",
            f"No food with id {food_id} exists.",
        )


class InsufficientStockError(ConflictError):
    """Exception raised when an outflow exceeds an establishment's stock.

    Carries the food and the two quantities so a client can tell the user what
    is actually available rather than only that the request failed.

    Args:
        food_id (str): The food whose balance is short.
        requested (str): The quantity the outflow asked for.
        available (str): The quantity actually held.
    """

    error_type = "insufficient-stock"

    def __init__(self, food_id: str, requested: str, available: str):
        super().__init__(
            "Insufficient stock",
            f"The establishment holds {available} of food {food_id}, "
            f"which does not cover the requested {requested}.",
            extensions={
                "food_id": food_id,
                "requested": requested,
                "available": available,
            },
        )
