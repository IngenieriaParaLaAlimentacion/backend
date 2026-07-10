from abc import ABC, abstractmethod

from app.repositories.activity_repository import ActivityRepository
from app.repositories.email_verification_repository import (
    EmailVerificationTokenRepository,
)
from app.repositories.establishment_repository import EstablishmentRepository
from app.repositories.measurement_alert_repository import MeasurementAlertRepository
from app.repositories.measurement_repository import MeasurementRepository
from app.repositories.password_recovery_repository import (
    PasswordRecoveryTokenRepository,
)
from app.repositories.subject_event_repository import SubjectEventRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.survey_repository import SurveyRepository
from app.repositories.user_establishment_repository import UserEstablishmentRepository
from app.repositories.user_password_repository import UserPasswordRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_token_repository import TokenRepository


class IUnitOfWork(ABC):
    activity_repo: ActivityRepository
    user_repo: UserRepository
    password_repo: UserPasswordRepository
    token_repo: TokenRepository
    establishment_repo: EstablishmentRepository
    user_establishment_repo: UserEstablishmentRepository
    subject_repo: SubjectRepository
    subject_event_repo: SubjectEventRepository
    password_recovery_repo: PasswordRecoveryTokenRepository
    email_verification_repo: EmailVerificationTokenRepository
    measurement_repo: MeasurementRepository
    measurement_alert_repo: MeasurementAlertRepository
    survey_repo: SurveyRepository

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *args):
        if exc_type:
            await self.rollback()
        await self.close()

    @abstractmethod
    async def close(self) -> None: ...
