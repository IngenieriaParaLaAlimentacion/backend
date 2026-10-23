import uuid
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import structlog

from app.config.settings import settings
from app.core.interfaces.llm_client import ILlmClient
from app.core.interfaces.object_storage import IObjectStorage
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_intake import FoodIntakeDomain
from app.domain.printed_quantity import parse_printed_quantity
from app.domain.unit_conversion import ConversionFactors, prefill_from_printed
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    ImageContentMismatchError,
    ImageTooLargeError,
    LlmClientError,
    ObjectStorageError,
    ReceiptPhotoStorageError,
    UnsupportedImageTypeError,
)
from app.models.food_catalog.food import Food
from app.schemas.common import IdentifierRefSchema
from app.schemas.food_intakes.food_intake_schema import FoodIntakeRequest
from app.schemas.food_intakes.receipt_schema import (
    ProposedFoodLine,
    ReceiptProposalResponse,
)
from app.services.access import check_establishment_access
from app.services.food_intakes.food_intake_service import FoodIntakeService

logger = structlog.get_logger()

_JPEG_MAGIC_BYTES = b"\xff\xd8\xff"
_PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF_MAGIC_BYTES = b"RIFF"
_WEBP_FORMAT_MARKER = b"WEBP"

_EXTRACTION_PROMPT = (
    "You are reading a photo of a store receipt for a community kitchen in "
    "Argentina. List every line item that is a food or beverage, in the "
    "order it appears. Ignore totals, taxes, discounts, payment methods, "
    "and store header/footer information. For each item, return its "
    "description exactly as printed on the receipt, but leave out any price "
    "shown on the line (unit price, line total, or a discount amount) -- "
    "there is no field for it, and its exact position and format vary by "
    "store, so it must not be left inside the description text. If the line "
    "also states a quantity (e.g. a weight, volume, or unit count such as "
    "'1kg', '900ml', 'x3'), also return that quantity as a number and the "
    "unit text exactly as printed (e.g. 'kg', 'ml', 'un'); leave both null "
    "when the line does not state a quantity."
)

_EXTRACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "raw_quantity": {"type": "number", "nullable": True},
                    "raw_unit_text": {"type": "string", "nullable": True},
                },
                "required": ["description", "raw_quantity", "raw_unit_text"],
            },
        }
    },
    "required": ["lines"],
}


class ReceiptIntakeService:
    """Assisted registration of a food intake from a photo of the receipt."""

    # Shown when the extractor finds nothing to propose -- either because the
    # receipt truly had no food lines, or because the LLM call itself failed
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

    @staticmethod
    def _validate_magic_bytes(data: bytes, content_type: str) -> bool:
        """Check whether the leading bytes of a file match the expected format.

        Inspect the actual file bytes (magic numbers) to verify the file is
        what it claims to be, rather than trusting the client-declared
        ``content_type`` header, which is trivially spoofable.

        Returns True if the bytes match the declared type, False otherwise.
        """
        if content_type == "image/jpeg":
            return data.startswith(_JPEG_MAGIC_BYTES)
        if content_type == "image/png":
            return data.startswith(_PNG_MAGIC_BYTES)
        if content_type == "image/webp":
            return (
                len(data) >= 12
                and data.startswith(_WEBP_RIFF_MAGIC_BYTES)
                and data[8:12] == _WEBP_FORMAT_MARKER
            )
        return False

    def _validate_image(self, content_type: str | None, data: bytes) -> None:
        """Reject an upload whose type or size the server will not process.

        Checked before any DB access and before the bytes are handed anywhere,
        so a junk upload is cheap to turn away.

        Raises:
            UnsupportedImageTypeError: content type not in the configured
                allow-list (also covers a missing content type).
            ImageTooLargeError: body larger than
                ``settings.receipt_image_max_bytes``.
            ImageContentMismatchError: the declared content type passes the
                allow-list, but the file's magic bytes say otherwise.
        """
        allowed = settings.receipt_image_allowed_types
        if content_type not in allowed:
            raise UnsupportedImageTypeError(content_type, sorted(allowed))
        if len(data) > settings.receipt_image_max_bytes:
            raise ImageTooLargeError(len(data), settings.receipt_image_max_bytes)
        if not self._validate_magic_bytes(data, content_type):
            raise ImageContentMismatchError(content_type)

    async def _build_lines(
        self, raw_lines: list[dict[str, Any]]
    ) -> list[ProposedFoodLine]:
        """Build the proposed lines from the extracted receipt items.

        The catalog match of each item is delegated entirely to
        ``FoodRepository.find_best_match`` (trigram similarity, ADR-0017). The
        conversion factors of every matched food are read in one query.
        """
        foods = [
            await self.uow.food_repo.find_best_match(
                raw["description"],
                settings.receipt_food_match_min_word_similarity,
                settings.receipt_food_match_min_similarity,
            )
            for raw in raw_lines
        ]
        factors = await self.uow.food_equivalence_repo.get_factors_by_food_ids(
            {food.id for food in foods if food is not None}
        )
        return [
            self._build_line(raw, food, factors)
            for raw, food in zip(raw_lines, foods, strict=True)
        ]

    @staticmethod
    def _build_line(
        raw: dict[str, Any],
        food: Food | None,
        factors: Mapping[UUID, ConversionFactors],
    ) -> ProposedFoodLine:
        """Build one proposed line from an extracted receipt item and its match.

        For a matched line, ``quantity`` and ``unit`` are prefilled together
        with the printed quantity converted to the food's base unit (see
        ``prefill_from_printed``), and both stay None when it cannot be.
        ``factors`` holds the conversion factors of the matched food.
        """
        raw_quantity = parse_printed_quantity(raw.get("raw_quantity"))
        raw_unit_text = raw.get("raw_unit_text")

        quantity = None
        unit = None
        if food is not None:
            prefill = prefill_from_printed(
                raw_quantity, raw_unit_text, food.base_unit, factors[food.id]
            )
            if prefill is not None:
                quantity, unit = prefill

        return ProposedFoodLine(
            description=raw["description"],
            food=IdentifierRefSchema.model_validate(food) if food is not None else None,
            quantity=quantity,
            unit=unit,
            raw_quantity=raw_quantity,
            raw_unit_text=raw_unit_text,
            needs_review=True,
        )

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
        """Validate a receipt photo and return the LLM-proposed food lines.

        Nothing is stored here: the image is only held in memory for this
        request. It is only persisted to R2 if and when the user confirms via
        ``POST /food-intakes/from-photo/confirm`` -- so an abandoned or
        rejected proposal never leaves an orphaned object in storage.

        Each line is matched against the food catalog by name similarity
        (ADR-0017); ``food`` is set when a confident match is found, and left
        ``None`` otherwise. On a match, ``quantity`` and ``unit`` are
        prefilled from the printed quantity converted to the food's base
        unit, when it can be. ``needs_review`` is always ``True`` --
        matching never marks a line as resolved, since the last validation
        before this data hits establishment stock is always the user's. When
        the extractor finds nothing, or the LLM call itself fails, the
        response falls back to an empty proposal with a hint to enter the
        intake manually rather than surfacing the failure as an error.

        Raises:
            UnsupportedImageTypeError: image type not accepted.
            ImageTooLargeError: image over the size ceiling.
            ImageContentMismatchError: the file's bytes do not match the
                declared content type.
            EstablishmentNotFoundError: ``establishment_id`` does not exist.
            EstablishmentAccessDeniedError: field worker without approved
                access to the establishment.
        """
        self._validate_image(content_type, image)

        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        await check_establishment_access(self.uow, actor, establishment_id)

        try:
            result = await self.llm_client.complete(
                prompt=_EXTRACTION_PROMPT,
                response_schema=_EXTRACTION_RESPONSE_SCHEMA,
                image=image,
                image_content_type=content_type,
            )
        except LlmClientError as exc:
            logger.warning(
                "receipt_intake_llm_failed",
                establishment_id=str(establishment_id),
                error=str(exc),
            )
            return ReceiptProposalResponse(
                establishment_id=establishment_id,
                lines=[],
                message=self._MANUAL_FALLBACK_MESSAGE,
            )

        lines = await self._build_lines(result["lines"])
        if not lines:
            logger.info(
                "receipt_intake_no_lines_found",
                establishment_id=str(establishment_id),
            )
            return ReceiptProposalResponse(
                establishment_id=establishment_id,
                lines=[],
                message=self._MANUAL_FALLBACK_MESSAGE,
            )

        return ReceiptProposalResponse(establishment_id=establishment_id, lines=lines)

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
            ImageContentMismatchError: the file's bytes do not match the
                declared content type.
            EstablishmentNotFoundError: ``establishment_id`` does not exist.
            EstablishmentAccessDeniedError: field worker without approved
                access to the establishment.
            ReceiptPhotoStorageError: the storage backend rejected the save.
            FoodNotFoundError: a line references a food that does not exist.
        """
        self._validate_image(content_type, image)

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
