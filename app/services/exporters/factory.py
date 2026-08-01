from enum import Enum

from app.services.exporters.base import SurveyResponseExporter
from app.services.exporters.xlsx_exporter import XlsxSurveyResponseExporter


class ExportFormat(str, Enum):
    XLSX = "xlsx"


_EXPORTERS: dict[ExportFormat, type[SurveyResponseExporter]] = {
    ExportFormat.XLSX: XlsxSurveyResponseExporter,
}


def get_exporter(format: ExportFormat) -> SurveyResponseExporter:
    return _EXPORTERS[format]()
