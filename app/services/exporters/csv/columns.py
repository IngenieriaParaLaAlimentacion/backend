"""Column specs for the exportable listing views.

Each spec's headers and their order mirror the columns of the corresponding
UI table, so an exported file lines up with the screen it came from. Keeping
them all in one module makes that correspondence reviewable at a glance.

Every ``latest_measurement`` is optional on the subject listing — a subject who
has never been measured exports blank timestamp and elapsed-time cells.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from app.domain.establishment import EstablishmentDomain
from app.domain.establishment_dashboard import EstablishmentSubjectItemDomain
from app.domain.food_stock import FoodStockItemDomain
from app.domain.measurement import MeasurementBase, MeasurementListItemDomain
from app.domain.measurement_assessment import AssessmentStatus, Indicator
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
    normalize_cell,
)
from app.services.exporters.csv.subject_time import (
    format_current_age,
    format_measurement_elapsed,
)
from app.utils.dates import ARGENTINA_TZ


def _latest(subject: SubjectDetailDomain, attribute: str):
    """Read an attribute off a subject's latest measurement, or None."""
    measurement = subject.latest_measurement
    return getattr(measurement, attribute) if measurement is not None else None


def build_subject_listing_export(
    reference: datetime | None = None,
    *,
    assessment_fields: bool = False,
) -> tuple[CsvExporter[SubjectDetailDomain], str]:
    """Build a subject exporter and filename for one reference instant."""
    reference = reference if reference is not None else datetime.now(timezone.utc)
    columns: tuple[CsvColumn[SubjectDetailDomain], ...] = (
        CsvColumn("Nombre", lambda s: format_person(s.name, s.last_name)),
        CsvColumn("Documento", lambda s: format_int(s.dni)),
        CsvColumn("Fecha de nacimiento", lambda s: format_date(s.birth_date)),
        CsvColumn("Edad", lambda s: format_current_age(s.birth_date, reference)),
        CsvColumn(
            "Último relevamiento",
            lambda s: format_datetime(_latest(s, "measured_at")),
        ),
        CsvColumn(
            "Tiempo desde el último relevamiento",
            lambda s: format_measurement_elapsed(_latest(s, "measured_at"), reference),
        ),
    )
    day = reference.astimezone(ARGENTINA_TZ).date()
    if assessment_fields:
        columns += _assessment_columns(lambda row: row.latest_measurement)
    exporter = CsvExporter(columns, entity_name="sujetos")
    return exporter, exporter.filename(day=day)


ESTABLISHMENT_COLUMNS: tuple[CsvColumn[EstablishmentDomain], ...] = (
    CsvColumn("Nombre", lambda e: normalize_cell(e.name)),
    CsvColumn("Dirección", lambda e: normalize_cell(e.formatted_address)),
    CsvColumn("Ciudad", lambda e: normalize_cell(e.city)),
    CsvColumn("Provincia", lambda e: normalize_cell(e.province)),
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
    CsvColumn("Comedor", lambda m: normalize_cell(m.establishment.name)),
    CsvColumn(
        "Responsable",
        lambda m: format_person(m.responsible.name, m.responsible.last_name),
    ),
    CsvColumn("Alertas", lambda m: format_alerts(m.alerts)),
    CsvColumn("Observación", lambda m: normalize_cell(m.observation)),
)

SURVEY_COLUMNS: tuple[CsvColumn[SurveyListItemDomain], ...] = (
    CsvColumn("Nombre", lambda s: normalize_cell(s.name)),
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

_Row = TypeVar("_Row")
_INDICATOR_LABELS = {
    Indicator.LENGTH_FOR_AGE: "Longitud para la edad",
    Indicator.WEIGHT_FOR_AGE: "Peso para la edad",
    Indicator.BMI_FOR_AGE: "IMC para la edad",
    Indicator.HEIGHT_FOR_AGE: "Talla para la edad",
    Indicator.ADULT_BMI: "IMC adulto",
}
_ASSESSMENT_STATUS_LABELS = {
    AssessmentStatus.EVALUATED: "Evaluado",
    AssessmentStatus.INSUFFICIENT_DATA: "Sin datos suficientes",
    AssessmentStatus.NOT_APPLICABLE: "No aplica",
}


def _assessment_columns(
    get_measurement: Callable[[_Row], MeasurementBase | None],
) -> tuple[CsvColumn[_Row], ...]:
    columns = []
    for indicator, label in _INDICATOR_LABELS.items():

        def assessment(row, indicator=indicator):
            measurement = get_measurement(row)
            return next(
                (
                    entry
                    for entry in (
                        (measurement.assessments or ()) if measurement else ()
                    )
                    if entry.indicator == indicator
                ),
                None,
            )

        columns.extend(
            (
                CsvColumn(
                    f"{label} · Estado",
                    lambda row, find=assessment: (
                        _ASSESSMENT_STATUS_LABELS[value.status]
                        if (value := find(row))
                        else ""
                    ),
                ),
                CsvColumn(
                    f"{label} · Clasificación",
                    lambda row, find=assessment: (
                        (value.classification or "") if (value := find(row)) else ""
                    ),
                ),
                CsvColumn(
                    f"{label} · Puntaje Z",
                    lambda row, find=assessment: (
                        format_decimal(value.z_score) if (value := find(row)) else ""
                    ),
                ),
                CsvColumn(
                    f"{label} · Alerta",
                    lambda row, find=assessment: (
                        normalize_cell(value.alert.detail)
                        if (value := find(row)) and value.alert
                        else ""
                    ),
                ),
            )
        )
    return tuple(columns)


ESTABLISHMENT_LISTING_EXPORTER = CsvExporter(
    ESTABLISHMENT_COLUMNS, entity_name="establecimientos"
)
MEASUREMENT_LISTING_EXPORTER = CsvExporter(
    MEASUREMENT_COLUMNS, entity_name="mediciones"
)
MEASUREMENT_ASSESSMENT_EXPORTER = CsvExporter(
    MEASUREMENT_COLUMNS + _assessment_columns(lambda row: row),
    entity_name="mediciones",
)
SURVEY_LISTING_EXPORTER = CsvExporter(SURVEY_COLUMNS, entity_name="encuestas")
ESTABLISHMENT_SUBJECT_EXPORTER = CsvExporter(
    ESTABLISHMENT_SUBJECT_COLUMNS, entity_name="sujetos"
)
ESTABLISHMENT_SUBJECT_ASSESSMENT_EXPORTER = CsvExporter(
    ESTABLISHMENT_SUBJECT_COLUMNS
    + _assessment_columns(lambda row: row.latest_measurement),
    entity_name="sujetos",
)


FOOD_STOCK_COLUMNS: tuple[CsvColumn[FoodStockItemDomain], ...] = (
    CsvColumn("Alimento", lambda s: normalize_cell(s.food.name)),
    CsvColumn("Categoría", lambda s: normalize_cell(s.category.name)),
    CsvColumn("Cantidad", lambda s: format_decimal(s.quantity, 3)),
    CsvColumn("Unidad", lambda s: normalize_cell(s.unit.value)),
    CsvColumn("Última actualización", lambda s: format_datetime(s.updated_at)),
)

FOOD_STOCK_EXPORTER = CsvExporter(FOOD_STOCK_COLUMNS, entity_name="stock")
