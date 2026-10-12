from typing import Any, NamedTuple

from opentelemetry.sdk._logs.export import LogRecordExporter, LogRecordExportResult


class FakeSpan:
    """Recording span stand-in that keeps the attributes set on it."""

    def __init__(self, attributes: dict) -> None:
        self.attributes = dict(attributes)

    def is_recording(self) -> bool:
        return True

    def set_attribute(self, key: str, value: str) -> None:
        self.attributes[key] = value


class ExportedLog(NamedTuple):
    body: Any
    attributes: dict


class SnapshotLogExporter(LogRecordExporter):
    """Exporter that keeps a copy of each record's body and attributes."""

    # Copying at export time matters: a processor that runs after the exporter
    # could still edit the shared record, which would hide a wrong order.
    def __init__(self) -> None:
        self.records: list[ExportedLog] = []

    def export(self, batch) -> LogRecordExportResult:
        for item in batch:
            record = item.log_record
            self.records.append(ExportedLog(record.body, dict(record.attributes)))
        return LogRecordExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
