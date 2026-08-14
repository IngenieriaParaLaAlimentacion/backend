"""FAO Food Insecurity Experience Scale (FIES) survey template.

Canonical 8-item FIES instrument used to pre-fill the backoffice survey-authoring
form. It is a read-only draft: the author supplies the survey ``name`` and may adjust
wording before saving. Nothing here is persisted until the author submits a create
request, and FIES is intentionally *not* a distinct survey type (see ADR-0002) — once
saved it is an ordinary survey.

The draft defaults to ``response_target=ANONYMOUS`` (see ADR-0007): FIES measures food
insecurity at the level of a household, which is neither a ``Subject`` nor an
``Establishment``. The author can still change it before the first response is recorded.

Variant: individual referent, 12-month reference period (FAO offers household and
30-day variants; adjust the preamble and pronouns if the program standardizes on one
of those). The "Sí"/"No" dichotomy matches FAO scoring (Sí = 1, No = 0). FAO field
instruments also offer a "No sabe / No responde" code; it is omitted because the
answering flow and FIES scoring are out of scope.

FAO short labels are kept as comments for traceability only — they are not persisted
(no per-question origin marker, per ADR-0002).

Sources:
  - FAO, *La escala de experiencia de inseguridad alimentaria (FIES)*.
  - Validated Spanish item wording + FAO labels (Salud Pública de México, SciELO).
  - DANE (Colombia) FIES nota metodológica.
"""

from app.domain.survey import ResponseType, SurveyResponseTarget
from app.schemas.survey_schema import (
    SurveyTemplateResponse,
    TemplateOption,
    TemplateQuestion,
)

# Reference-period preamble; each item reads as a completion of it.
_FIES_PREAMBLE = (
    "Durante los últimos 12 meses, hubo alguna vez en que, por falta de dinero u "
    "otros recursos:"
)

# (FAO short label, Spanish item wording) in canonical FAO order.
_FIES_ITEMS: list[tuple[str, str]] = [
    ("WORRIED", "¿Le preocupó no tener suficientes alimentos para comer?"),
    ("HEALTHY", "¿No pudo comer alimentos sanos y nutritivos?"),
    ("FEWFOODS", "¿Comió poca variedad de alimentos?"),
    ("SKIPPED", "¿Tuvo que saltarse una comida?"),
    ("ATELESS", "¿Comió menos de lo que pensaba que debía comer?"),
    ("RANOUT", "¿Su hogar se quedó sin alimentos?"),
    ("HUNGRY", "¿Sintió hambre pero no comió?"),
    ("WHLDAY", "¿Dejó de comer durante todo un día?"),
]


def _dichotomous_options() -> list[TemplateOption]:
    return [
        TemplateOption(text="Sí", position=0),
        TemplateOption(text="No", position=1),
    ]


def build_fies_template() -> SurveyTemplateResponse:
    """Return a fresh FIES draft the backoffice can load into the create form."""
    return SurveyTemplateResponse(
        name="",
        description=_FIES_PREAMBLE,
        response_target=SurveyResponseTarget.ANONYMOUS,
        questions=[
            TemplateQuestion(
                text=text,
                response_type=ResponseType.SINGLE_CHOICE,
                is_required=True,
                position=position,
                options=_dichotomous_options(),
            )
            for position, (_label, text) in enumerate(_FIES_ITEMS)
        ],
    )
