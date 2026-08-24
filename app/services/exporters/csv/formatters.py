"""Value formatting for the listing CSV exports.

Every value in an exported CSV is rendered for an Argentine Excel/Google Sheets
user: dates as ``dd/mm/aaaa``, decimals with a comma, and enums as the Spanish
labels the UI shows. Because the CSV dialect uses ``;`` as its delimiter (see
``csv_exporter``), a decimal comma is unambiguous.

All formatters are None-safe and render a missing value as an empty cell, so a
column spec never has to guard before calling one.
"""

from collections.abc import Iterable
from datetime import date, datetime, timezone

from app.domain.measurement import AlertType, NutritionalStatus
from app.domain.subject import Sex
from app.domain.survey import SurveyResponseTarget
from app.utils.dates import ARGENTINA_TZ

_DATE_FORMAT = "%d/%m/%Y"
_DATETIME_FORMAT = "%d/%m/%Y %H:%M"

SEX_LABELS: dict[Sex, str] = {
    Sex.MALE: "Masculino",
    Sex.FEMALE: "Femenino",
}

NUTRITIONAL_STATUS_LABELS: dict[NutritionalStatus, str] = {
    NutritionalStatus.NORMAL: "Normal",
    NutritionalStatus.OVERWEIGHT: "Sobrepeso",
    NutritionalStatus.OBESE: "Obesidad",
    NutritionalStatus.WASTED: "Emaciación",
    NutritionalStatus.SEVERELY_WASTED: "Emaciación severa",
    NutritionalStatus.UNDERWEIGHT: "Bajo peso",
    NutritionalStatus.SEVERE_UNDERWEIGHT: "Bajo peso severo",
}

ALERT_TYPE_LABELS: dict[AlertType, str] = {
    AlertType.SEVERELY_WASTED: "Emaciación severa",
    AlertType.WASTED: "Emaciación",
    AlertType.OVERWEIGHT: "Sobrepeso",
    AlertType.OBESE: "Obesidad",
    AlertType.SEVERE_UNDERWEIGHT: "Bajo peso severo",
    AlertType.UNDERWEIGHT: "Bajo peso",
}

SURVEY_TARGET_LABELS: dict[SurveyResponseTarget, str] = {
    SurveyResponseTarget.SUBJECT: "Sujeto",
    SurveyResponseTarget.ESTABLISHMENT: "Establecimiento",
    SurveyResponseTarget.ANONYMOUS: "Anónima",
}


def format_date(value: date | None) -> str:
    """Render a date as ``dd/mm/aaaa``, or an empty cell when missing."""
    return value.strftime(_DATE_FORMAT) if value is not None else ""


def format_datetime(value: datetime | None) -> str:
    """Render a timestamp as ``dd/mm/aaaa hh:mm`` in Argentine local time.

    Naive timestamps are assumed to be UTC — that is how they are stored — so
    an exported time always matches what the UI shows.
    """
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ARGENTINA_TZ).strftime(_DATETIME_FORMAT)


def format_decimal(value: float | None, digits: int = 2) -> str:
    """Render a number with a decimal comma, e.g. ``18,52``.

    Formats with a dot and swaps the separator rather than going through the
    ``locale`` module, which is process-global and not thread-safe.
    """
    if value is None:
        return ""
    return f"{value:.{digits}f}".replace(".", ",")


def format_int(value: int | None) -> str:
    """Render an integer, or an empty cell when missing."""
    return str(value) if value is not None else ""


def format_age(age_months: int | None) -> str:
    """Render an age held in months as ``5a 3m``."""
    if age_months is None:
        return ""
    years, months = divmod(age_months, 12)
    return f"{years}a {months}m"


def format_bool(value: bool | None, true_label: str, false_label: str) -> str:
    """Render a flag with the pair of Spanish labels its column uses."""
    if value is None:
        return ""
    return true_label if value else false_label


def format_person(name: str | None, last_name: str | None) -> str:
    """Render a person's full name as a single cell."""
    return " ".join(part for part in (name, last_name) if part)


def join_values(values: Iterable[str]) -> str:
    """Join several values into one cell, comma-separated.

    Safe against the decimal comma: the dialect's delimiter is ``;``, and
    ``csv.writer`` quotes the cell if it ever contains one.
    """
    return ", ".join(value for value in values if value)


def format_sex(value: Sex | None) -> str:
    """Render a subject's sex in Spanish."""
    return SEX_LABELS[value] if value is not None else ""


def format_nutritional_status(value: NutritionalStatus | None) -> str:
    """Render a nutritional status in Spanish.

    None means the subject has never been measured, which is deliberately not
    the same as NORMAL and renders as an empty cell.
    """
    return NUTRITIONAL_STATUS_LABELS[value] if value is not None else ""


def format_alerts(alerts) -> str:
    """Render a measurement's alerts as one comma-separated cell."""
    return join_values(ALERT_TYPE_LABELS[alert.alert_type] for alert in alerts)


def format_survey_target(value: SurveyResponseTarget | None) -> str:
    """Render a survey's response target ("Alcance") in Spanish."""
    return SURVEY_TARGET_LABELS[value] if value is not None else ""
