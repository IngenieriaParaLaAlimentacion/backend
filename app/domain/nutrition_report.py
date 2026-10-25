from enum import StrEnum

# Longest text of a summary section or of one of its list items, in characters.
SUMMARY_TEXT_MAX_LENGTH = 700

# Most items a list of the summary may hold.
SUMMARY_MAX_ITEMS = 7


# Shown with every report. It is fixed text: the AI does not write it and it is not
# stored, so changing it applies to the reports already generated.
SCOPE_NOTE = (
    "Este informe evalúa el equilibrio nutricional de los alimentos que llegaron "
    "al comedor durante el mes. No conoce la dieta completa de los chicos, no "
    "indica si la cantidad alcanza y no reemplaza la evaluación de un nutricionista."
)


class SummaryStatus(StrEnum):
    """What became of the AI-written summary of a report."""

    GENERATED = "generated"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
