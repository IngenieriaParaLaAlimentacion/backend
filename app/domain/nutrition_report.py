from enum import StrEnum

# Longest text of a summary section or of one of its list items, in characters.
SUMMARY_TEXT_MAX_LENGTH = 700

# Most items a list of the summary may hold.
SUMMARY_MAX_ITEMS = 7


class SummaryStatus(StrEnum):
    """What became of the AI-written summary of a report."""

    GENERATED = "generated"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
