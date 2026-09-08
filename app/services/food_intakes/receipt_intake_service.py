from uuid import UUID

from app.config.settings import settings
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    ImageTooLargeError,
    UnsupportedImageTypeError,
)
from app.schemas.food_intakes.receipt_schema import ReceiptProposalResponse
from app.services.access import check_establishment_access


class ReceiptIntakeService:
    """Assisted registration of a food intake from a photo of the receipt."""

    # TODO: remove after. Returned while there is no extractor: every accepted 
    # upload comes back with no lines, so the client is told 
    # to fall back to manual entry
    _MANUAL_FALLBACK_MESSAGE = "No se pudieron extraer alimentos de la factura. " \
    "Porfavor carguelos de forma manual. "

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

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

    async def propose_from_photo(
        self,
        *,
        establishment_id: UUID,
        content_type: str | None,
        image: bytes,
        actor: UserActor,
    ) -> ReceiptProposalResponse:
        """Validate a receipt photo and return the (currently empty) proposal.

        The image is neither stored nor persisted: the caller reviews the
        proposal and submits the lines through the normal intake path with
        ``source = photo``.

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
