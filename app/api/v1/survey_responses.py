from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import get_survey_response_service, require_some
from app.domain import UserActor
from app.domain.user import UserRole
from app.schemas.survey_response_schema import (
    SurveyResponseEditRequest,
    SurveyResponseRequest,
    SurveyResponseResponse,
)
from app.services.survey_response_service import SurveyResponseService

router = APIRouter(prefix="/survey-responses")

_submitter_or_editor = require_some(
    UserRole.FIELD_WORKER, UserRole.ADMIN, UserRole.SUPERADMIN
)


@router.post(
    "",
    response_model=SurveyResponseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a survey response",
    description=(
        "Idempotent, offline-first submission of one anonymous individual's "
        "answers to a survey at an establishment. Replaying the same id returns the "
        "stored record unchanged. No draft mode: required questions must all "
        "be answered or the submission is rejected outright."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Response already existed; idempotent replay of the same id."
        },
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Answers invalid, or establishment outside the "
            "survey's audience"
        },
        status.HTTP_404_NOT_FOUND: {"description": "Survey or establishment not found"},
    },
)
async def submit_survey_response(
    data: SurveyResponseRequest,
    response: Response,
    actor: UserActor = Depends(_submitter_or_editor),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response, created = await service.submit(data, actor)
    if not created:
        response.status_code = status.HTTP_200_OK
    return SurveyResponseResponse.model_validate(survey_response)


@router.get(
    "/{response_id}",
    response_model=SurveyResponseResponse,
    summary="Get a survey response",
    description=(
        "Return a response's full detail, including its answers. Restricted to "
        "the original submitter or an admin/superadmin — the same actors allowed "
        "to edit it. Backs the mobile 'view a submitted response' screen reached "
        "from a `/me/activity` entry, which only carries a summary."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Response not found"},
    },
)
async def get_survey_response(
    response_id: UUID,
    actor: UserActor = Depends(_submitter_or_editor),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response = await service.get(response_id, actor)
    return SurveyResponseResponse.model_validate(survey_response)


@router.put(
    "/{response_id}",
    response_model=SurveyResponseResponse,
    summary="Edit a survey response",
    description=(
        "Full-replace edit of a response's answers. Restricted to the "
        "original submitter or an admin/superadmin. Idempotent per edit "
        "attempt id for offline-first retries."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {"description": "Answers invalid"},
        status.HTTP_404_NOT_FOUND: {"description": "Response not found"},
    },
)
async def edit_survey_response(
    response_id: UUID,
    data: SurveyResponseEditRequest,
    actor: UserActor = Depends(_submitter_or_editor),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response = await service.edit(response_id, data, actor)
    return SurveyResponseResponse.model_validate(survey_response)
