import uuid
from uuid import UUID

from app.config.settings import settings
from app.core.interfaces.llm_client import ILlmClient
from app.core.interfaces.object_storage import IObjectStorage
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_intake import FoodIntakeDomain
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    ImageTooLargeError,
    ObjectStorageError,
    ReceiptPhotoStorageError,
    UnsupportedImageTypeError,
)
from app.schemas.food_intakes.food_intake_schema import FoodIntakeRequest
from app.schemas.food_intakes.receipt_schema import ReceiptProposalResponse
from app.services.access import check_establishment_access
from app.services.food_intakes.food_intake_service import FoodIntakeService


class ReceiptIntakeService:
    """Assisted registration of a food intake from a photo of the receipt."""

    # TODO: remove after. Returned while there is no extractor: every accepted
    # upload comes back with no lines, so the client is told
    # to fall back to manual entry
    _MANUAL_FALLBACK_MESSAGE = (
        "No se pudieron extraer alimentos de la factura. "
        "Porfavor carguelos de forma manual. "
    )

    def __init__(
        self,
        uow: IUnitOfWork,
        storage: IObjectStorage,
        food_intake_service: FoodIntakeService,
        llm_client: ILlmClient,
    ) -> None:
        self.uow = uow
        self.storage = storage
        self.food_intake_service = food_intake_service
        self.llm_client = llm_client

    def _validate_image(self, content_type: str | None, size_bytes: int) -> None:
        """Reject an upload whose type or size the server will not process.

        Checked before any DB access and before the bytes are handed anywhere,
        so a junk upload is cheap to turn away.

        Raises:
            UnsupportedImageTypeError: content type not in the configured
                allow-list (also covers a missing content type).
            ImageTooLargeError: body larger than
                ``settings.receipt_image_max_bytes``.
        """
        allowed = settings.receipt_image_allowed_types
        if content_type not in allowed:
            raise UnsupportedImageTypeError(content_type, sorted(allowed))
        if size_bytes > settings.receipt_image_max_bytes:
            raise ImageTooLargeError(size_bytes, settings.receipt_image_max_bytes)

    @staticmethod
    def _build_photo_key(establishment_id: UUID, content_type: str) -> str:
        """A unique storage key, namespaced by establishment.

        The extension is the content type's subtype (``image/png`` -> ``.png``).

        A fresh UUID per upload means re-uploading the same photo (e.g. after
        a rejected proposal) never collides with the earlier attempt.
        """
        extension = content_type.split("/", 1)[-1]
        return f"food-intake-receipts/{establishment_id}/{uuid.uuid4()}.{extension}"

    async def propose_from_photo(
        self,
        *,
        establishment_id: UUID,
        content_type: str | None,
        image: bytes,
        actor: UserActor,
    ) -> ReceiptProposalResponse:
        """Validate a receipt photo and return the (currently empty) proposal.

        Nothing is stored here: the image is only held in memory for this
        request. It is only persisted to R2 if and when the user confirms via
        ``POST /food-intakes/from-photo/confirm`` -- so an abandoned or
        rejected proposal never leaves an orphaned object in storage.

        Raises:
            UnsupportedImageTypeError: image type not accepted.
            ImageTooLargeError: image over the size ceiling.
            EstablishmentNotFoundError: ``establishment_id`` does not exist.
            EstablishmentAccessDeniedError: field worker without approved
                access to the establishment.
        """
        self._validate_image(content_type, len(image))

        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        await check_establishment_access(self.uow, actor, establishment_id)

        return ReceiptProposalResponse(
            establishment_id=establishment_id,
            lines=[],
            message=self._MANUAL_FALLBACK_MESSAGE,
        )

    async def confirm_from_photo(
        self,
        *,
        data: FoodIntakeRequest,
        content_type: str | None,
        image: bytes,
        actor: UserActor,
    ) -> tuple[FoodIntakeDomain, bool]:
        """Validate the receipt photo, store it, and register the intake.

        Every check that would make registration fail runs *before* the photo
        is uploaded -- including the idempotency replay check -- so a retry, an
        unknown establishment, or a denied actor never leaves an orphaned
        object in R2. Only once all of that passes does the photo get saved
        and the intake created with the resulting key.

        Raises:
            UnsupportedImageTypeError: image type not accepted.
            ImageTooLargeError: image over the size ceiling.
            EstablishmentNotFoundError: ``establishment_id`` does not exist.
            EstablishmentAccessDeniedError: field worker without approved
                access to the establishment.
            ReceiptPhotoStorageError: the storage backend rejected the save.
            FoodNotFoundError: a line references a food that does not exist.
        """
        self._validate_image(content_type, len(image))

        if data.id is not None:
            existing = await self.uow.food_intake_repo.get_by_id(data.id)
            if existing is not None:
                return FoodIntakeDomain.from_db(existing), False

        await self.uow.establishment_repo.get_by_id_or_raise(data.establishment_id)
        await check_establishment_access(self.uow, actor, data.establishment_id)

        photo_key = self._build_photo_key(data.establishment_id, content_type)
        try:
            await self.storage.save(
                key=photo_key, content_type=content_type, data=image
            )
        except ObjectStorageError as exc:
            raise ReceiptPhotoStorageError() from exc

        return await self.food_intake_service.register(data, actor, photo_key=photo_key)
