"""Column specs for the five exportable listing views.

Each spec's headers and their order mirror the columns of the corresponding
UI table, so an exported file lines up with the screen it came from. Keeping
all five in one module makes that correspondence reviewable at a glance.

Every ``latest_measurement`` is optional on the subject listing — a subject who
has never been measured exports blank measurement cells rather than being
dropped from the file.
"""

from app.domain.establishment import EstablishmentDomain
from app.domain.establishment_dashboard import EstablishmentSubjectItemDomain
from app.domain.measurement import MeasurementListItemDomain
from app.domain.subject_detail import SubjectDetailDomain
from app.domain.survey import SurveyListItemDomain
from app.services.exporters.csv.csv_exporter import CsvColumn, CsvExporter
from app.services.exporters.csv.formatters import (
    format_age,
    format_alerts,
    format_bool,
    format_date,
    format_datetime,
    format_decimal,
    format_int,
    format_nutritional_status,
    format_person,
    format_survey_target,
)


def _latest(subject: SubjectDetailDomain, attribute: str):
    """Read an attribute off a subject's latest measurement, or None."""
    measurement = subject.latest_measurement
    return getattr(measurement, attribute) if measurement is not None else None


SUBJECT_COLUMNS: tuple[CsvColumn[SubjectDetailDomain], ...] = (
    CsvColumn("Nombre", lambda s: format_person(s.name, s.last_name)),
    CsvColumn("Documento", lambda s: format_int(s.dni)),
    CsvColumn("Fecha de nacimiento", lambda s: format_date(s.birth_date)),
    CsvColumn(
        "Último relevamiento",
        lambda s: format_datetime(_latest(s, "measured_at")),
    ),
)

ESTABLISHMENT_COLUMNS: tuple[CsvColumn[EstablishmentDomain], ...] = (
    CsvColumn("Nombre", lambda e: e.name),
    CsvColumn("Dirección", lambda e: e.formatted_address),
    CsvColumn("Ciudad", lambda e: e.city),
    CsvColumn("Provincia", lambda e: e.province),
)

MEASUREMENT_COLUMNS: tuple[CsvColumn[MeasurementListItemDomain], ...] = (
    CsvColumn("Peso (kg)", lambda m: format_decimal(m.weight_kg)),
    CsvColumn("Talla (cm)", lambda m: format_decimal(m.height_cm)),
    CsvColumn("IMC", lambda m: format_decimal(m.bmi)),
    CsvColumn("Fecha", lambda m: format_datetime(m.measured_at)),
    CsvColumn(
        "Sujeto",
        lambda m: format_person(m.subject.name, m.subject.last_name),
    ),
    CsvColumn("Comedor", lambda m: m.establishment.name),
    CsvColumn(
        "Responsable",
        lambda m: format_person(m.responsible.name, m.responsible.last_name),
    ),
    CsvColumn("Alertas", lambda m: format_alerts(m.alerts)),
)

SURVEY_COLUMNS: tuple[CsvColumn[SurveyListItemDomain], ...] = (
    CsvColumn("Nombre", lambda s: s.name),
    CsvColumn("Alcance", lambda s: format_survey_target(s.response_target)),
    CsvColumn("Estado", lambda s: format_bool(s.is_active, "Activa", "Inactiva")),
    CsvColumn("Cantidad de preguntas", lambda s: format_int(s.question_count)),
    CsvColumn("Fecha de creación", lambda s: format_datetime(s.created_at)),
)

ESTABLISHMENT_SUBJECT_COLUMNS: tuple[CsvColumn[EstablishmentSubjectItemDomain], ...] = (
    CsvColumn("Nombre", lambda s: format_person(s.name, s.last_name)),
    CsvColumn("Documento", lambda s: format_int(s.dni)),
    CsvColumn("Edad", lambda s: format_age(s.age_months)),
    CsvColumn(
        "Último relevamiento",
        lambda s: format_datetime(s.latest_measurement.measured_at),
    ),
    CsvColumn("Peso (kg)", lambda s: format_decimal(s.latest_measurement.weight_kg)),
    CsvColumn("Talla (cm)", lambda s: format_decimal(s.latest_measurement.height_cm)),
    CsvColumn("IMC", lambda s: format_decimal(s.latest_measurement.bmi)),
    CsvColumn("Estado", lambda s: format_nutritional_status(s.nutritional_status)),
)


SUBJECT_LISTING_EXPORTER = CsvExporter(SUBJECT_COLUMNS, entity_name="sujetos")
ESTABLISHMENT_LISTING_EXPORTER = CsvExporter(
    ESTABLISHMENT_COLUMNS, entity_name="establecimientos"
)
MEASUREMENT_LISTING_EXPORTER = CsvExporter(
    MEASUREMENT_COLUMNS, entity_name="mediciones"
)
SURVEY_LISTING_EXPORTER = CsvExporter(SURVEY_COLUMNS, entity_name="encuestas")
ESTABLISHMENT_SUBJECT_EXPORTER = CsvExporter(
    ESTABLISHMENT_SUBJECT_COLUMNS, entity_name="sujetos"
)
