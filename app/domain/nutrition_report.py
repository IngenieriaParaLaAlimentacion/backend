from enum import StrEnum

# Longest summary the AI may return, in characters.
SUMMARY_MAX_LENGTH = 3000


class SummaryStatus(StrEnum):
    """What became of the AI-written summary of a report."""

    GENERATED = "generated"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
