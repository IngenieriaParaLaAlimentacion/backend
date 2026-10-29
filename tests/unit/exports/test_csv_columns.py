"""Pins the exported row for each of the five listing column specs.

These are the tests that catch a column drifting out of sync with the UI
table: header text, header order, and how a sparse row renders.
"""

import asyncio
import csv
import io
import uuid
from datetime import date, datetime, timezone

from app.domain.establishment import EstablishmentDomain
from app.domain.establishment_dashboard import EstablishmentSubjectItemDomain
from app.domain.measurement import (
    AlertDomain,
    AlertSeverity,
    AlertType,
    EstablishmentRefDomain,
    MeasurementListItemDomain,
    MeasurementSummaryDomain,
    NutritionalStatus,
    ResponsibleRefDomain,
    SubjectRefDomain,
)
from app.domain.subject import Sex
from app.domain.subject_detail import SubjectDetailDomain
from app.domain.survey import SurveyListItemDomain, SurveyResponseTarget
from app.services.exporters.csv.columns import (
    ESTABLISHMENT_LISTING_EXPORTER,
    ESTABLISHMENT_SUBJECT_EXPORTER,
    MEASUREMENT_LISTING_EXPORTER,
    SURVEY_LISTING_EXPORTER,
    build_subject_listing_export,
)

# 10:30 UTC -> 07:30 in Buenos Aires.
MEASURED_AT = datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc)


def _rows(exporter, items) -> list[str]:
    """Export and return the file's lines, header included."""
    return exporter.export(items).decode("utf-8-sig").strip("\r\n").split("\r\n")


def _establishment_ref() -> EstablishmentRefDomain:
    return EstablishmentRefDomain(
        id=uuid.uuid4(), name="Comedor La Unión", city="Rosario", province="Santa Fe"
    )


def _alert(alert_type: AlertType = AlertType.OBESE) -> AlertDomain:
    return AlertDomain(
        id=uuid.uuid4(),
        measurement_id=uuid.uuid4(),
        alert_type=alert_type,
        severity=AlertSeverity.HIGH,
        detail="IMC alto",
        created_at=MEASURED_AT,
    )


def _summary(alerts=None) -> MeasurementSummaryDomain:
    return MeasurementSummaryDomain(
        id=uuid.uuid4(),
        measured_at=MEASURED_AT,
        weight_kg=18.5,
        height_cm=105.25,
        bmi=16.716,
        alerts=alerts if alerts is not None else [],
        establishment=_establishment_ref(),
    )


def _subject_detail(measured: bool = True) -> SubjectDetailDomain:
    return SubjectDetailDomain(
        id=uuid.uuid4(),
        dni=30123456,
        sex=Sex.FEMALE,
        name="Ana",
        last_name="Pérez",
        birth_date=date(2015, 3, 14),
        is_rural=False,
        is_indigenous=False,
        nutritional_status=NutritionalStatus.NORMAL if measured else None,
        latest_measurement=_summary() if measured else None,
    )


class TestSubjectColumns:
    REFERENCE = datetime(2026, 6, 14, 15, tzinfo=timezone.utc)

    def test_headers_match_the_ui_fields(self):
        exporter, filename = build_subject_listing_export(self.REFERENCE)
        assert exporter.headers == (
            "Nombre",
            "Documento",
            "Fecha de nacimiento",
            "Edad",
            "Último relevamiento",
            "Tiempo desde el último relevamiento",
        )
        assert filename == "sujetos_2026-06-14.csv"

    def test_populated_subject(self):
        exporter, _ = build_subject_listing_export(self.REFERENCE)
        _, row = _rows(exporter, [_subject_detail()])
        assert row == (
            "Ana Pérez;30123456;14/03/2015;11a 3m;14/03/2026 07:30;hace 3 meses"
        )

    def test_never_measured_subject_keeps_blank_timestamp_and_elapsed(self):
        exporter, _ = build_subject_listing_export(self.REFERENCE)
        _, row = _rows(exporter, [_subject_detail(measured=False)])
        assert row == "Ana Pérez;30123456;14/03/2015;11a 3m;;"

    def test_empty_export_has_all_six_headers(self):
        exporter, _ = build_subject_listing_export(self.REFERENCE)
        assert _rows(exporter, []) == [";".join(exporter.headers)]

    async def test_stream_and_filename_keep_one_reference_across_midnight(
        self, monkeypatch
    ):
        clock = [datetime(2026, 10, 29, 2, 59, 59, tzinfo=timezone.utc)]
        samples = []

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                samples.append(clock[0])
                return clock[0]

        monkeypatch.setattr("app.services.exporters.csv.columns.datetime", Clock)
        exporter, filename = build_subject_listing_export()
        subject = _subject_detail()
        subject.birth_date = date(2008, 4, 29)
        subject.latest_measurement.measured_at = datetime(
            2026, 10, 28, 15, tzinfo=timezone.utc
        )

        async def rows():
            yield subject
            clock[0] = datetime(2026, 10, 29, 3, 0, 1, tzinfo=timezone.utc)
            yield subject

        data = b"".join([chunk async for chunk in exporter.stream(rows())])
        assert data == exporter.export([subject, subject])
        parsed = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))
        assert [row[3:] for row in parsed[1:]] == [
            ["18a 5m", "28/10/2026 12:00", "hoy"],
            ["18a 5m", "28/10/2026 12:00", "hoy"],
        ]
        assert filename == "sujetos_2026-10-28.csv"
        assert len(samples) == 1

    async def test_concurrent_exporters_keep_independent_references(self):
        before, before_name = build_subject_listing_export(
            datetime(2026, 10, 29, 2, 59, 59, tzinfo=timezone.utc)
        )
        after, after_name = build_subject_listing_export(
            datetime(2026, 10, 29, 3, 0, 1, tzinfo=timezone.utc)
        )
        subject = _subject_detail()
        subject.birth_date = date(2008, 4, 29)
        subject.latest_measurement.measured_at = datetime(
            2026, 10, 28, 15, tzinfo=timezone.utc
        )

        async def render(exporter):
            async def rows():
                await asyncio.sleep(0)
                yield subject

            return b"".join([chunk async for chunk in exporter.stream(rows())])

        before_data, after_data = await asyncio.gather(render(before), render(after))
        assert b"18a 5m;28/10/2026 12:00;hoy" in before_data
        assert b"18a 6m;28/10/2026 12:00;hace 1 d" in after_data
        assert before_name == "sujetos_2026-10-28.csv"
        assert after_name == "sujetos_2026-10-29.csv"


class TestEstablishmentColumns:
    def test_headers_match_the_ui_table(self):
        assert ESTABLISHMENT_LISTING_EXPORTER.headers == (
            "Nombre",
            "Dirección",
            "Ciudad",
            "Provincia",
        )

    def test_row(self):
        establishment = EstablishmentDomain(
            id=uuid.uuid4(),
            name="Comedor La Unión",
            formatted_address="San Martín 123",
            latitude=-32.9,
            longitude=-60.6,
            place_id="place-1",
            city="Rosario",
            province="Santa Fe",
        )
        _, row = _rows(ESTABLISHMENT_LISTING_EXPORTER, [establishment])
        assert row == "Comedor La Unión;San Martín 123;Rosario;Santa Fe"


class TestMeasurementColumns:
    def _measurement(self, alerts=None) -> MeasurementListItemDomain:
        return MeasurementListItemDomain(
            id=uuid.uuid4(),
            measured_at=MEASURED_AT,
            weight_kg=18.5,
            height_cm=105.25,
            bmi=16.716,
            alerts=alerts if alerts is not None else [],
            subject=SubjectRefDomain(
                id=uuid.uuid4(),
                dni=30123456,
                sex=Sex.FEMALE,
                name="Ana",
                last_name="Pérez",
                birth_date=date(2015, 3, 14),
            ),
            establishment=_establishment_ref(),
            responsible=ResponsibleRefDomain(
                id=uuid.uuid4(), name="Juan", last_name="Gómez"
            ),
        )

    def test_headers_match_the_ui_table(self):
        assert MEASUREMENT_LISTING_EXPORTER.headers == (
            "Peso (kg)",
            "Talla (cm)",
            "IMC",
            "Fecha",
            "Sujeto",
            "Comedor",
            "Responsable",
            "Alertas",
            "Observación",
        )

    def test_row_with_no_alerts(self):
        _, row = _rows(MEASUREMENT_LISTING_EXPORTER, [self._measurement()])
        assert row == (
            "18,50;105,25;16,72;14/03/2026 07:30;Ana Pérez;"
            "Comedor La Unión;Juan Gómez;;"
        )

    def test_alerts_are_joined_into_one_cell(self):
        # The join uses ", " and needs no quoting: the delimiter is ";", so a
        # comma inside a cell is unambiguous.
        measurement = self._measurement(
            alerts=[_alert(AlertType.OBESE), _alert(AlertType.UNDERWEIGHT)]
        )
        _, row = _rows(MEASUREMENT_LISTING_EXPORTER, [measurement])
        assert row.endswith(";Obesidad, Bajo peso;")
        assert row.count(";") == 8  # 9 columns, no stray delimiter from the join

    def test_observation_is_exported_as_one_cell(self):
        measurement = self._measurement()
        measurement.observation = 'Sin calzado; dijo "repetir".\nPróximo control.'
        output = MEASUREMENT_LISTING_EXPORTER.export([measurement]).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(output), delimiter=";"))
        assert rows[0][-1] == "Observación"
        assert len(rows[1]) == 9
        assert rows[1][-1] == 'Sin calzado; dijo "repetir". Próximo control.'


class TestSurveyColumns:
    def _survey(self, is_active: bool = True) -> SurveyListItemDomain:
        return SurveyListItemDomain(
            id=uuid.uuid4(),
            name="FIES 2026",
            response_target=SurveyResponseTarget.SUBJECT,
            requires_response_number=True,
            is_active=is_active,
            created_by_id=uuid.uuid4(),
            question_count=8,
            response_count=42,
            created_at=MEASURED_AT,
        )

    def test_headers_match_the_ui_table(self):
        assert SURVEY_LISTING_EXPORTER.headers == (
            "Nombre",
            "Alcance",
            "Estado",
            "Cantidad de preguntas",
            "Fecha de creación",
        )

    def test_active_survey(self):
        _, row = _rows(SURVEY_LISTING_EXPORTER, [self._survey()])
        assert row == "FIES 2026;Sujeto;Activa;8;14/03/2026 07:30"

    def test_inactive_survey(self):
        _, row = _rows(SURVEY_LISTING_EXPORTER, [self._survey(is_active=False)])
        assert ";Inactiva;" in row


class TestEstablishmentSubjectColumns:
    def _item(self) -> EstablishmentSubjectItemDomain:
        return EstablishmentSubjectItemDomain(
            id=uuid.uuid4(),
            dni=30123456,
            name="Ana",
            last_name="Pérez",
            sex=Sex.FEMALE,
            birth_date=date(2015, 3, 14),
            age_months=63,
            measurement_count=3,
            nutritional_status=NutritionalStatus.OVERWEIGHT,
            latest_measurement=_summary(),
        )

    def test_headers_match_the_ui_table(self):
        assert ESTABLISHMENT_SUBJECT_EXPORTER.headers == (
            "Nombre",
            "Documento",
            "Edad",
            "Último relevamiento",
            "Peso (kg)",
            "Talla (cm)",
            "IMC",
            "Estado",
        )

    def test_row(self):
        _, row = _rows(ESTABLISHMENT_SUBJECT_EXPORTER, [self._item()])
        assert row == (
            "Ana Pérez;30123456;5a 3m;14/03/2026 07:30;18,50;105,25;16,72;Sobrepeso"
        )
