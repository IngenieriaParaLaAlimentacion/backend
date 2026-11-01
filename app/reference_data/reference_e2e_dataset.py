"""Fictitious reference dataset for E2E runs and user-manual screenshots.

Every person, credential and organisation here is made up. The establishments are
named after public squares, so their addresses are real places but no real
organisation is attributed to them. ``seed_reference_e2e.py`` loads it.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.food_intake import FoodIntakeOriginType
from app.domain.food_outflow import FoodOutflowCategory
from app.domain.subject import Sex
from app.domain.user import UserRole, UserStatus

# Every reference user logs in with this password.
PASSWORD = "Referencia-123!"

# Fixed, so the same key always gives the same id and a second run finds its rows.
_NAMESPACE = uuid.UUID("0b0f6c1e-5a52-4f0e-9d0e-6a3d6c1f2b84")


def reference_id(*parts: str) -> uuid.UUID:
    """Return the id the dataset gives to the record named by ``parts``."""
    return uuid.uuid5(_NAMESPACE, "/".join(parts))


@dataclass(frozen=True)
class ReferenceUser:
    """A user, with the establishments it may work in."""

    key: str
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus = UserStatus.ACTIVE
    approved_establishments: tuple[str, ...] = ()
    pending_establishments: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceEstablishment:
    """A community kitchen, placed at the centre of a public square."""

    key: str
    name: str
    formatted_address: str
    city: str
    province: str
    latitude: float
    longitude: float
    # How big its deliveries are, relative to the others.
    stock_scale: float

    @property
    def place_id(self) -> str:
        """The identifier the establishment is stored under."""
        return f"reference-{self.key}"


@dataclass(frozen=True)
class ReferenceEstablishmentRequest:
    """A request, still pending, to add an establishment."""

    key: str
    requested_by: str
    name: str
    formatted_address: str
    city: str
    province: str


@dataclass(frozen=True)
class Reading:
    """One weighing and measuring of a subject."""

    days_ago: int
    weight_kg: float
    height_cm: float


@dataclass(frozen=True)
class ReferenceSubject:
    """A person measured at an establishment, aged 25 or less."""

    key: str
    dni: int
    sex: Sex
    name: str
    last_name: str
    age_years: int
    # Days past the last birthday, so birthdays do not all fall on one date.
    days_past_birthday: int
    establishment: str
    readings: tuple[Reading, ...]
    is_rural: bool = False
    is_indigenous: bool = False

    def birth_date(self, today: date) -> date:
        """Return the date of birth that makes the subject this old today."""
        days = round(self.age_years * 365.25) + self.days_past_birthday
        return today - timedelta(days=days)


@dataclass(frozen=True)
class IntakeTemplate:
    """A delivery every establishment receives, scaled to its size."""

    key: str
    days_ago: int
    origin_type: FoodIntakeOriginType
    is_recurring: bool
    comments: str
    # (catalog food code, quantity in the food's base unit)
    items: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class OutflowTemplate:
    """Food every establishment takes out, scaled to its size."""

    key: str
    days_ago: int
    category: FoodOutflowCategory
    comments: str
    items: tuple[tuple[str, int], ...]


USERS = (
    ReferenceUser(
        key="admin",
        email="admin.referencia@tpp.com",
        name="Adriana",
        last_name="Referencia",
        role=UserRole.ADMIN,
    ),
    ReferenceUser(
        key="analyst",
        email="analista.referencia@tpp.com",
        name="Andrés",
        last_name="Referencia",
        role=UserRole.ANALYST,
        approved_establishments=(
            "caba",
            "cordoba",
            "mendoza",
            "salta",
            "resistencia",
            "bariloche",
        ),
    ),
    ReferenceUser(
        key="field_worker_1",
        email="relevador1.referencia@tpp.com",
        name="Rocío",
        last_name="Referencia",
        role=UserRole.FIELD_WORKER,
        approved_establishments=("caba", "cordoba"),
    ),
    ReferenceUser(
        key="field_worker_2",
        email="relevador2.referencia@tpp.com",
        name="Ramiro",
        last_name="Referencia",
        role=UserRole.FIELD_WORKER,
        approved_establishments=("mendoza", "salta"),
    ),
    ReferenceUser(
        key="field_worker_3",
        email="relevador3.referencia@tpp.com",
        name="Renata",
        last_name="Referencia",
        role=UserRole.FIELD_WORKER,
        approved_establishments=("resistencia", "bariloche"),
    ),
    # Verified its email and waits for an admin; it cannot log in yet.
    ReferenceUser(
        key="pending_field_worker",
        email="pendiente.referencia@tpp.com",
        name="Paula",
        last_name="Referencia",
        role=UserRole.FIELD_WORKER,
        status=UserStatus.PENDING_VALIDATION,
        pending_establishments=("caba",),
    ),
)

ESTABLISHMENTS = (
    ReferenceEstablishment(
        key="caba",
        name="Comedor Plaza de Mayo",
        formatted_address="Plaza de Mayo, Ciudad Autónoma de Buenos Aires, Argentina",
        city="Ciudad Autónoma de Buenos Aires",
        province="Ciudad Autónoma de Buenos Aires",
        latitude=-34.6083,
        longitude=-58.3712,
        stock_scale=1.5,
    ),
    ReferenceEstablishment(
        key="cordoba",
        name="Comedor San Martín",
        formatted_address="Plaza San Martín, Córdoba, Argentina",
        city="Córdoba",
        province="Córdoba",
        latitude=-31.4201,
        longitude=-64.1888,
        stock_scale=1.2,
    ),
    ReferenceEstablishment(
        key="mendoza",
        name="Comedor Independencia",
        formatted_address="Plaza Independencia, Mendoza, Argentina",
        city="Mendoza",
        province="Mendoza",
        latitude=-32.8895,
        longitude=-68.8458,
        stock_scale=1.0,
    ),
    ReferenceEstablishment(
        key="salta",
        name="Comedor 9 de Julio",
        formatted_address="Plaza 9 de Julio, Salta, Argentina",
        city="Salta",
        province="Salta",
        latitude=-24.7883,
        longitude=-65.4106,
        stock_scale=1.1,
    ),
    ReferenceEstablishment(
        key="resistencia",
        name="Comedor 25 de Mayo",
        formatted_address="Plaza 25 de Mayo, Resistencia, Chaco, Argentina",
        city="Resistencia",
        province="Chaco",
        latitude=-27.4511,
        longitude=-58.9867,
        stock_scale=0.9,
    ),
    ReferenceEstablishment(
        key="bariloche",
        name="Comedor Centro Cívico",
        formatted_address=(
            "Centro Cívico, San Carlos de Bariloche, Río Negro, Argentina"
        ),
        city="San Carlos de Bariloche",
        province="Río Negro",
        latitude=-41.1335,
        longitude=-71.3103,
        stock_scale=0.8,
    ),
)

ESTABLISHMENT_REQUESTS = (
    ReferenceEstablishmentRequest(
        key="la_plata",
        requested_by="field_worker_1",
        name="Comedor Plaza Moreno",
        formatted_address="Plaza Moreno, La Plata, Buenos Aires, Argentina",
        city="La Plata",
        province="Buenos Aires",
    ),
    ReferenceEstablishmentRequest(
        key="tucuman",
        requested_by="field_worker_3",
        name="Comedor Plaza Independencia",
        formatted_address=(
            "Plaza Independencia, San Miguel de Tucumán, Tucumán, Argentina"
        ),
        city="San Miguel de Tucumán",
        province="Tucumán",
    ),
)

# DNIs start well above any real one, so they never meet a person's.
SUBJECTS = (
    ReferenceSubject(
        key="valentina",
        dni=90_000_001,
        sex=Sex.FEMALE,
        name="Valentina",
        last_name="Gómez",
        age_years=2,
        days_past_birthday=40,
        establishment="caba",
        readings=(
            Reading(330, 9.4, 77.0),
            Reading(170, 10.5, 82.0),
            Reading(20, 11.6, 86.5),
        ),
    ),
    ReferenceSubject(
        key="mateo",
        dni=90_000_002,
        sex=Sex.MALE,
        name="Mateo",
        last_name="Rodríguez",
        age_years=4,
        days_past_birthday=120,
        establishment="caba",
        readings=(
            Reading(300, 13.8, 93.0),
            Reading(150, 15.0, 98.0),
            Reading(25, 16.2, 103.0),
        ),
    ),
    ReferenceSubject(
        key="camila",
        dni=90_000_003,
        sex=Sex.FEMALE,
        name="Camila",
        last_name="Fernández",
        age_years=7,
        days_past_birthday=200,
        establishment="caba",
        readings=(
            Reading(320, 20.0, 113.0),
            Reading(160, 21.8, 117.5),
            Reading(15, 23.6, 121.0),
        ),
    ),
    ReferenceSubject(
        key="joaquin",
        dni=90_000_004,
        sex=Sex.MALE,
        name="Joaquín",
        last_name="López",
        age_years=9,
        days_past_birthday=75,
        establishment="cordoba",
        readings=(
            Reading(340, 31.0, 128.0),
            Reading(170, 35.5, 131.5),
            Reading(30, 39.5, 134.0),
        ),
    ),
    ReferenceSubject(
        key="lucia",
        dni=90_000_005,
        sex=Sex.FEMALE,
        name="Lucía",
        last_name="Martínez",
        age_years=12,
        days_past_birthday=300,
        establishment="cordoba",
        readings=(
            Reading(310, 38.0, 147.0),
            Reading(150, 41.5, 151.0),
            Reading(10, 44.0, 154.0),
        ),
    ),
    ReferenceSubject(
        key="benjamin",
        dni=90_000_006,
        sex=Sex.MALE,
        name="Benjamín",
        last_name="Pérez",
        age_years=3,
        days_past_birthday=90,
        establishment="mendoza",
        readings=(
            Reading(330, 11.0, 85.0),
            Reading(170, 12.2, 90.0),
            Reading(20, 13.1, 94.0),
        ),
    ),
    ReferenceSubject(
        key="isabella",
        dni=90_000_007,
        sex=Sex.FEMALE,
        name="Isabella",
        last_name="Díaz",
        age_years=5,
        days_past_birthday=160,
        establishment="mendoza",
        readings=(
            Reading(300, 13.0, 97.0),
            Reading(150, 13.2, 101.0),
            Reading(30, 13.4, 106.5),
        ),
    ),
    ReferenceSubject(
        key="thiago",
        dni=90_000_008,
        sex=Sex.MALE,
        name="Thiago",
        last_name="Sosa",
        age_years=10,
        days_past_birthday=20,
        establishment="mendoza",
        readings=(
            Reading(320, 27.0, 133.0),
            Reading(160, 29.0, 137.0),
            Reading(20, 31.0, 140.0),
        ),
        is_rural=True,
        is_indigenous=True,
    ),
    ReferenceSubject(
        key="martina",
        dni=90_000_009,
        sex=Sex.FEMALE,
        name="Martina",
        last_name="Romero",
        age_years=14,
        days_past_birthday=250,
        establishment="salta",
        readings=(
            Reading(300, 47.0, 156.0),
            Reading(150, 49.0, 158.0),
            Reading(20, 50.5, 159.0),
        ),
        is_indigenous=True,
    ),
    ReferenceSubject(
        key="lautaro",
        dni=90_000_010,
        sex=Sex.MALE,
        name="Lautaro",
        last_name="Torres",
        age_years=16,
        days_past_birthday=110,
        establishment="salta",
        readings=(
            Reading(330, 58.0, 168.0),
            Reading(170, 61.0, 171.0),
            Reading(25, 64.0, 173.0),
        ),
        is_rural=True,
    ),
    ReferenceSubject(
        key="agustina",
        dni=90_000_011,
        sex=Sex.FEMALE,
        name="Agustina",
        last_name="Álvarez",
        age_years=1,
        days_past_birthday=30,
        establishment="resistencia",
        readings=(
            Reading(250, 6.4, 61.0),
            Reading(130, 8.0, 69.0),
            Reading(20, 9.3, 74.0),
        ),
    ),
    ReferenceSubject(
        key="nicolas",
        dni=90_000_012,
        sex=Sex.MALE,
        name="Nicolás",
        last_name="Herrera",
        age_years=19,
        days_past_birthday=60,
        establishment="resistencia",
        readings=(
            Reading(320, 62.0, 172.0),
            Reading(160, 63.5, 172.0),
            Reading(20, 65.0, 172.0),
        ),
    ),
    ReferenceSubject(
        key="florencia",
        dni=90_000_013,
        sex=Sex.FEMALE,
        name="Florencia",
        last_name="Castro",
        age_years=22,
        days_past_birthday=180,
        establishment="resistencia",
        readings=(
            Reading(300, 44.0, 160.0),
            Reading(150, 45.5, 160.0),
            Reading(20, 46.5, 160.0),
        ),
        is_rural=True,
    ),
    ReferenceSubject(
        key="matias",
        dni=90_000_014,
        sex=Sex.MALE,
        name="Matías",
        last_name="Ruiz",
        age_years=24,
        days_past_birthday=140,
        establishment="bariloche",
        readings=(
            Reading(310, 92.0, 175.0),
            Reading(150, 94.0, 175.0),
            Reading(20, 95.0, 175.0),
        ),
    ),
    ReferenceSubject(
        key="julieta",
        dni=90_000_015,
        sex=Sex.FEMALE,
        name="Julieta",
        last_name="Acosta",
        age_years=25,
        days_past_birthday=10,
        establishment="bariloche",
        readings=(
            Reading(320, 68.0, 165.0),
            Reading(160, 70.0, 165.0),
            Reading(20, 72.0, 165.0),
        ),
    ),
)

INTAKES = (
    IntakeTemplate(
        key="dry_goods",
        days_ago=75,
        origin_type=FoodIntakeOriginType.MUNICIPAL_GOVERNMENT,
        is_recurring=True,
        comments="Mercadería seca del programa municipal",
        items=(
            ("arroz_blanco_crudo", 25),
            ("fideos_secos_crudos", 20),
            ("harina_de_trigo_cruda", 30),
            ("lentejas_crudas", 10),
        ),
    ),
    IntakeTemplate(
        key="fresh",
        days_ago=40,
        origin_type=FoodIntakeOriginType.FOUNDATION,
        is_recurring=False,
        comments="Verduras, fruta y huevos donados",
        items=(
            ("cebolla_cruda", 8),
            ("zanahoria_cruda", 8),
            ("tomate_crudo", 6),
            ("banana", 5),
            ("huevo_de_gallina_entero_crudo", 60),
        ),
    ),
    IntakeTemplate(
        key="dairy",
        days_ago=12,
        origin_type=FoodIntakeOriginType.PRIVATE_COMPANY,
        is_recurring=True,
        comments="Aporte mensual de una empresa",
        items=(
            ("leche_entera_fluida_con_vitaminas_a_y_d", 20),
            ("arroz_blanco_crudo", 15),
            ("huevo_de_gallina_entero_crudo", 30),
            ("manzana_con_piel", 6),
        ),
    ),
)

# Smaller than the stock every establishment holds when it is registered.
OUTFLOWS = (
    OutflowTemplate(
        key="kitchen",
        days_ago=30,
        category=FoodOutflowCategory.KITCHEN,
        comments="Almuerzo de la semana",
        items=(
            ("arroz_blanco_crudo", 6),
            ("fideos_secos_crudos", 5),
            ("lentejas_crudas", 2),
            ("cebolla_cruda", 2),
        ),
    ),
    OutflowTemplate(
        key="families",
        days_ago=8,
        category=FoodOutflowCategory.FAMILY_DELIVERY,
        comments="Entrega de bolsones a familias",
        items=(
            ("harina_de_trigo_cruda", 5),
            ("huevo_de_gallina_entero_crudo", 12),
            ("leche_entera_fluida_con_vitaminas_a_y_d", 4),
        ),
    ),
)

FIES_SURVEY_NAME = "Encuesta FIES de referencia"

# How many of the eight FIES items each response answers "Sí" to, in the
# canonical order, from food secure to severely food insecure.
FIES_SCORES = (0, 1, 2, 2, 3, 4, 5, 6, 7, 8)
