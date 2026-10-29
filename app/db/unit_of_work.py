import app.db.database as _db
from app.core.interfaces.unit_of_work import IUnitOfWork
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
from app.repositories.nutrition_reports.nutrition_report_repository import (
    NutritionReportRepository,
)
from app.repositories.recipes.recipe_repository import RecipeRepository
from app.repositories.subjects.subject_event_repository import SubjectEventRepository
from app.repositories.subjects.subject_repository import SubjectRepository
from app.repositories.surveys.survey_repository import SurveyRepository
from app.repositories.surveys.survey_response_edit_repository import (
    SurveyResponseEditRepository,
)
from app.repositories.surveys.survey_response_repository import SurveyResponseRepository


class UnitOfWork(IUnitOfWork):
    """Concrete UnitOfWork backed by an AsyncSession.

    Usage:
        async with UnitOfWork() as uow:
            uow.user_repo.create(...)
            await uow.commit()
    """

    async def __aenter__(self):
        """Open a new async session and initialize all repositories."""
        self.session = _db.AsyncSessionLocal()
        self.recipe_repo = RecipeRepository(self.session)
        self.user_repo = UserRepository(self.session)
        self.password_repo = UserPasswordRepository(self.session)
        self.token_repo = TokenRepository(self.session)
        self.establishment_repo = EstablishmentRepository(self.session)
        self.establishment_request_repo = EstablishmentRequestRepository(self.session)
        self.user_establishment_repo = UserEstablishmentRepository(self.session)
        self.subject_repo = SubjectRepository(self.session)
        self.subject_event_repo = SubjectEventRepository(self.session)
        self.password_recovery_repo = PasswordRecoveryTokenRepository(self.session)
        self.email_verification_repo = EmailVerificationTokenRepository(self.session)
        self.measurement_repo = MeasurementRepository(self.session)
        self.measurement_alert_repo = MeasurementAlertRepository(self.session)
        self.activity_repo = ActivityRepository(self.session)
        self.survey_repo = SurveyRepository(self.session)
        self.survey_response_repo = SurveyResponseRepository(self.session)
        self.survey_response_edit_repo = SurveyResponseEditRepository(self.session)
        self.establishment_dashboard_repo = EstablishmentDashboardRepository(
            self.session
        )
        self.food_category_repo = FoodCategoryRepository(self.session)
        self.gapa_food_category_repo = GapaFoodCategoryRepository(self.session)
        self.nutrient_repo = NutrientRepository(self.session)
        self.food_repo = FoodRepository(self.session)
        self.food_nutrient_value_repo = FoodNutrientValueRepository(self.session)
        self.food_equivalence_repo = FoodEquivalenceRepository(self.session)
        self.food_intake_repo = FoodIntakeRepository(self.session)
        self.food_outflow_repo = FoodOutflowRepository(self.session)
        self.food_stock_repo = FoodStockRepository(self.session)
        self.nutrition_report_repo = NutritionReportRepository(self.session)
        self.push_device_repo = UserPushDeviceRepository(self.session)
        self.stale_cycle_repo = StaleEstablishmentCycleRepository(self.session)
        self.push_delivery_job_repo = PushDeliveryJobRepository(self.session)
        self.health_repo = HealthRepository(self.session)
        return self

    async def commit(self) -> None:
        """Persist all pending changes to the database."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Discard all pending changes since the last commit."""
        await self.session.rollback()

    async def close(self) -> None:
        """Release the session back to the connection pool."""
        await self.session.close()
