<!-- GENERATED FILE - do not edit by hand.
     Run: poetry run python docs/generate_error_catalog.py -->

# Error catalog

Every error response is `application/problem+json`. The `type` member below is the
stable, machine-readable identifier: **branch on it**. `title` and `detail` are
human-readable prose and may be reworded at any time.

The catalog is additive-only: new values may be added, existing values are not
renamed or removed without notice.

Some errors also carry RFC 7807 extension members alongside the canonical five,
such as `user_id` or `relation_status`.

Five `type` values are produced by the framework rather than by a domain
exception and so are not in the registry: `/errors/validation-failed` (422),
`/errors/http-error` (400, a request body that is not valid UTF-8),
`/errors/not-found` (404, unrouted path), `/errors/method-not-allowed` (405) and
`/errors/internal-error` (500).

| `type` | Status | Exception | Description |
|---|---|---|---|
| `/errors/account-pending-validation` | 403 | `PendingValidationError` | Exception raised when a user attempts to log in with a pending account. |
| `/errors/admin/invite-already-pending` | 409 | `InvitePendingError` | Raised when inviting an address that already has a pending invitation. |
| `/errors/auth/invalid-recovery-token` | 401 | `InvalidRecoveryTokenError` | Raised when a password recovery token is unusable. |
| `/errors/auth/invalid-refresh-token` | 401 | `InvalidRefreshTokenError` | Raised when a refresh token is unknown, expired or already revoked. |
| `/errors/auth/invalid-verification-token` | 401 | `InvalidVerificationTokenError` | Raised when an email verification token is unusable. |
| `/errors/auth/missing-token` | 401 | `MissingTokenError` | Raised when a protected endpoint receives no bearer token at all. |
| `/errors/auth/recovery-token-expired` | 401 | `RecoveryTokenExpiredError` | Raised when a password recovery token is past its expiry. |
| `/errors/auth/recovery-token-used` | 401 | `RecoveryTokenUsedError` | Raised when a password recovery token has already been consumed. |
| `/errors/auth/verification-token-expired` | 401 | `VerificationTokenExpiredError` | Raised when an email verification token is past its expiry. |
| `/errors/auth/verification-token-used` | 401 | `VerificationTokenUsedError` | Raised when an email verification token has already been consumed. |
| `/errors/email-delivery-failed` | 502 | `EmailDeliveryError` | Raised when an outbound email cannot be delivered to the SMTP server. |
| `/errors/establishment-access-denied` | 403 | `EstablishmentAccessDeniedError` | Raised when a field worker acts on an establishment they have no approved relation with. |
| `/errors/establishment-already-exists` | 409 | `EstablishmentAlreadyExistsError` | Raised when an establishment with the given place_id already exists. |
| `/errors/establishment-not-found` | 404 | `EstablishmentNotFoundError` | Exception raised when an establishment is not found. |
| `/errors/establishment-request-already-reviewed` | 409 | `EstablishmentRequestAlreadyReviewedError` | Raised when approving/rejecting a request that is no longer pending. |
| `/errors/establishment-request-not-found` | 404 | `EstablishmentRequestNotFoundError` | Exception raised when an establishment request does not exist. |
| `/errors/export/unmapped-label` | 400 | `UnmappedExportLabelError` | Exception raised when a CSV export hits an enum value with no label. |
| `/errors/field-worker-is-not-pending` | 400 | `FieldWorkerNotPendingError` | Raised when a field worker is not awaiting validation. |
| `/errors/filter-not-applicable` | 400 | `FilterNotApplicableError` | Raised when a filter resolves through a target the resource does not carry. |
| `/errors/food-movement-not-found` | 404 | `FoodMovementNotFoundError` | Exception raised when a food movement cannot be found in an establishment. |
| `/errors/food-not-found` | 404 | `FoodNotFoundError` | Exception raised when a food cannot be found. |
| `/errors/image-content-mismatch` | 422 | `ImageContentMismatchError` | Raised when an image's bytes do not match its declared content type. |
| `/errors/image-too-large` | 422 | `ImageTooLargeError` | Raised when an uploaded image is larger than the configured ceiling. |
| `/errors/insufficient-stock` | 409 | `InsufficientStockError` | Exception raised when an outflow exceeds an establishment's stock. |
| `/errors/invalid-age-range` | 400 | `InvalidAgeRangeError` | Raised when an age-range filter has a minimum above its maximum. |
| `/errors/invalid-credentials` | 401 | `InvalidCredentialsError` | Exception raised when credentials are invalid. |
| `/errors/invalid-date-range` | 400 | `InvalidDateRangeError` | Raised when a date-range filter starts after it ends. |
| `/errors/invalid-response-number-range` | 400 | `InvalidNumberRangeError` | Raised when a response-number-range filter starts above where it ends. |
| `/errors/invalid-survey-payload` | 400 | `InvalidSurveyPayloadError` | Exception raised when a reconcile payload references ids outside the survey. |
| `/errors/invalid-survey-response` | 400 | `InvalidSurveyResponseError` | Exception raised when submitted answers fail validation, or the payload names an entity that does not match the survey's response target. |
| `/errors/invalid-survey-structure` | 400 | `InvalidSurveyStructureError` | Exception raised when a survey's questions or options are inconsistent. |
| `/errors/invalid-user-role` | 400 | `InvalidUserRoleError` | Raised when the target user's role is not valid for the operation. |
| `/errors/no-fields-to-update` | 400 | `EmptyUpdateRequestError` | Exception raised when an update has no attributes to be updated. |
| `/errors/not-resource-owner` | 403 | `NotResourceOwnerError` | Raised when a non-admin acts on a resource somebody else created. |
| `/errors/notification-configuration-invalid` | 503 | `NotificationConfigurationError` | Raised when scheduled notifications are not fully configured. |
| `/errors/password-not-found` | 404 | `PasswordNotFoundError` | Exception raised when a user's password record is not found. |
| `/errors/rate-limited` | 429 | `RateLimitedError` | Raised when a caller exceeds the rate limit of a public endpoint. |
| `/errors/receipt-photo-storage-failed` | 502 | `ReceiptPhotoStorageError` | Raised when a receipt photo cannot be persisted to object storage. |
| `/errors/role-not-allowed` | 403 | `RoleNotAllowedError` | Raised when the actor's role is not permitted to perform the operation. |
| `/errors/subject-already-exists` | 409 | `SubjectAlreadyExistsError` | Exception raised when trying to register a subject with an existing DNI. |
| `/errors/subject-not-found` | 404 | `SubjectNotFoundError` | Exception raised when a subject cannot be found. |
| `/errors/survey-already-exists` | 409 | `SurveyAlreadyExistsError` | Exception raised when a survey name collides with an existing one. |
| `/errors/survey-locked` | 409 | `SurveyLockedError` | Exception raised when an edit to a survey with recorded responses would invalidate them. |
| `/errors/survey-not-available` | 403 | `SurveyNotAvailableError` | Raised when a field worker reaches a survey that is not currently active. |
| `/errors/survey-not-found` | 404 | `SurveyNotFoundError` | Exception raised when a survey cannot be found. |
| `/errors/survey-response-already-exists` | 409 | `SurveyResponseAlreadyExistsError` | Exception raised when a survey's target has already been answered. |
| `/errors/survey-response-not-found` | 404 | `SurveyResponseNotFoundError` | Exception raised when a survey response cannot be found. |
| `/errors/unauthorized` | 401 | `UnauthorizedError` | Exception raised when authorization fails. |
| `/errors/unsupported-image-type` | 422 | `UnsupportedImageTypeError` | Raised when an uploaded image's content type is not in the allow-list. |
| `/errors/user-already-exists` | 409 | `UserAlreadyExistsError` | Exception raised when trying to register with an existing email. |
| `/errors/user-establishment-not-approved` | 409 | `UserEstablishmentNotApprovedError` | Raised when revoking access to an establishment that isn't currently approved for the given user. |
| `/errors/user-establishment-not-found` | 404 | `UserEstablishmentNotFoundError` | Exception raised when a user-establishment relation does not exist. |
| `/errors/user-establishment-not-withdrawable` | 409 | `UserEstablishmentNotWithdrawableError` | Raised when a user tries to withdraw their own access to an establishment whose relation is not currently approved or pending. |
| `/errors/user-is-not-a-field-worker` | 400 | `UserNotFieldWorkerError` | Raised when the target user's role is not one the operation accepts: a field worker, or also an analyst for establishment access revocation. |
| `/errors/user-is-not-active` | 400 | `UserNotActiveError` | Raised when an operation requires the target user to be active. |
| `/errors/user-is-not-pending` | 400 | `UserNotPendingError` | Raised when a user has no pending invitation. |
| `/errors/user-not-found` | 404 | `UserNotFoundError` | Exception raised when a user is not found. |
