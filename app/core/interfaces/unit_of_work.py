from abc import ABC, abstractmethod

from app.repositories.activity_repository import ActivityRepository
from app.repositories.auth.email_verification_repository import (
    EmailVerificationTokenRepository,
)
from app.repositories.auth.password_recovery_repository import (
    PasswordRecoveryTokenRepository,
)
from app.repositories.auth.user_establishment_repository import (
    UserEstablishmentRepository,
)
from app.repositories.auth.user_password_repository import UserPasswordRepository
from app.repositories.auth.user_repository import UserRepository
from app.repositories.auth.user_token_repository import TokenRepository
from app.repositories.establishments.establishment_dashboard_repository import (
    EstablishmentDashboardRepository,
)
from app.repositories.establishments.establishment_repository import (
    EstablishmentRepository,
)
from app.repositories.establishments.establishment_request_repository import (
    EstablishmentRequestRepository,
)
from app.repositories.food_catalog.food_category_repository import (
    FoodCategoryRepository,
)
from app.repositories.food_catalog.food_equivalence_repository import (
    FoodEquivalenceRepository,
)
from app.repositories.food_catalog.food_nutrient_value_repository import (
    FoodNutrientValueRepository,
)
from app.repositories.food_catalog.food_repository import FoodRepository
from app.repositories.food_catalog.gapa_food_category_repository import (
    GapaFoodCategoryRepository,
)
from app.repositories.food_catalog.nutrient_repository import NutrientRepository
from app.repositories.food_intakes.food_intake_repository import FoodIntakeRepository
from app.repositories.food_outflows.food_outflow_repository import (
    FoodOutflowRepository,
)
from app.repositories.food_stock.food_stock_repository import FoodStockRepository
from app.repositories.health_repository import HealthRepository
from app.repositories.measurements.measurement_alert_repository import (
    MeasurementAlertRepository,
)
from app.repositories.measurements.measurement_repository import MeasurementRepository
from app.repositories.notifications import (
    PushDeliveryJobRepository,
    StaleEstablishmentCycleRepository,
    UserPushDeviceRepository,
)
from app.repositories.subjects.subject_event_repository import SubjectEventRepository
from app.repositories.subjects.subject_repository import SubjectRepository
from app.repositories.surveys.survey_repository import SurveyRepository
from app.repositories.surveys.survey_response_edit_repository import (
    SurveyResponseEditRepository,
)
from app.repositories.surveys.survey_response_repository import SurveyResponseRepository


class IUnitOfWork(ABC):
    activity_repo: ActivityRepository
    user_repo: UserRepository
    password_repo: UserPasswordRepository
    token_repo: TokenRepository
    establishment_repo: EstablishmentRepository
    establishment_request_repo: EstablishmentRequestRepository
    user_establishment_repo: UserEstablishmentRepository
    subject_repo: SubjectRepository
    subject_event_repo: SubjectEventRepository
    password_recovery_repo: PasswordRecoveryTokenRepository
    email_verification_repo: EmailVerificationTokenRepository
    measurement_repo: MeasurementRepository
    measurement_alert_repo: MeasurementAlertRepository
    survey_repo: SurveyRepository
    survey_response_repo: SurveyResponseRepository
    survey_response_edit_repo: SurveyResponseEditRepository
    establishment_dashboard_repo: EstablishmentDashboardRepository
    food_category_repo: FoodCategoryRepository
    gapa_food_category_repo: GapaFoodCategoryRepository
    nutrient_repo: NutrientRepository
    food_repo: FoodRepository
    food_nutrient_value_repo: FoodNutrientValueRepository
    food_equivalence_repo: FoodEquivalenceRepository
    food_intake_repo: FoodIntakeRepository
    food_outflow_repo: FoodOutflowRepository
    food_stock_repo: FoodStockRepository
    push_device_repo: UserPushDeviceRepository
    stale_cycle_repo: StaleEstablishmentCycleRepository
    push_delivery_job_repo: PushDeliveryJobRepository
    health_repo: HealthRepository

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
