from abc import ABC, abstractmethod

from app.domain.survey import SurveyDomain
from app.domain.survey_response import SurveyResponseDetailDomain


class SurveyResponseExporter(ABC):
    """Strategy interface for exporting a survey's responses at one
    establishment into a downloadable file. Implementations own their own
    file format and layout; callers only need content_type/file_extension
    to build the HTTP response. See ADR-00005 for the rationale."""

    @property
    @abstractmethod
    def content_type(self) -> str: ...

    @property
    @abstractmethod
    def file_extension(self) -> str: ...

    @abstractmethod
    def export(
        self,
        survey: SurveyDomain,
        responses: list[SurveyResponseDetailDomain],
    ) -> bytes:
        """Return the file's raw bytes for these responses."""
        ...
