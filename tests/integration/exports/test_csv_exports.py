"""End-to-end coverage for the five listing CSV export endpoints.

The through-line of every test here is parity: an export must carry the same
rows, in the same order, as the listing it was launched from -- just without
the pagination window.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from fastapi import status

from app.services.exporters.csv.columns import build_subject_listing_export
from tests.integration.helpers import bmi_for

BOM = b"\xef\xbb\xbf"


@pytest.fixture
def fixed_export_date(monkeypatch) -> date:
    """Use one deterministic date for filename generation and its expectation."""
    reference = datetime(2026, 8, 24, 15, tzinfo=timezone.utc)
    fixed_date = reference.date()
    monkeypatch.setattr(
        "app.services.exporters.csv.csv_exporter.today_in_argentina",
        lambda: fixed_date,
    )
    monkeypatch.setattr(
        "app.api.v1.subjects.build_subject_listing_export",
        lambda: build_subject_listing_export(reference),
    )
    return fixed_date


SUBJECTS_EXPORT_URL = "/api/v1/subjects/export"
ESTABLISHMENTS_EXPORT_URL = "/api/v1/establishments/export"
MEASUREMENTS_EXPORT_URL = "/api/v1/measurements/export"
SURVEYS_EXPORT_URL = "/api/v1/surveys/export"
ESTABLISHMENT_SUBJECTS_EXPORT_URL = "/api/v1/establishments/{id}/subjects/export"


def _lines(response) -> list[str]:
    """The exported file's lines, header included."""
    return response.content.decode("utf-8-sig").strip("\r\n").split("\r\n")


def _data_rows(response) -> list[str]:
    """The exported file's data lines, header excluded."""
    return _lines(response)[1:]


def _first_cells(response) -> list[str]:
    """The first column of every data row -- enough to pin ordering."""
    return [row.split(";")[0] for row in _data_rows(response)]


@dataclass
class Scenario:
    establishment_rosario: uuid.UUID
    establishment_cordoba: uuid.UUID
    subject_ana: uuid.UUID
    subject_beto: uuid.UUID
    subject_unmeasured: uuid.UUID
    survey_active: uuid.UUID


@pytest_asyncio.fixture
async def scenario(app) -> Scenario:
    """Seed two establishments, three subjects, two measurements, two surveys."""
    from app.db.database import AsyncSessionLocal
    from app.domain.subject import Sex
    from app.domain.survey import SurveyInstrumentType, SurveyResponseTarget
    from app.domain.user import UserStatus
    from app.models.auth.user import User
    from app.models.auth.user import UserRole as ORMUserRole
    from app.models.establishments.establishment import Establishment
    from app.models.measurements.measurement import Measurement
    from app.models.subjects.subject import Subject
    from app.models.surveys.survey import Survey

    async with AsyncSessionLocal() as session:
        est_rosario = Establishment(
            name="Comedor La Unión",
            formatted_address="San Martín 123",
            latitude=-32.9,
            longitude=-60.6,
            place_id=f"place-{uuid.uuid4().hex[:8]}",
            city="Rosario",
            province="Santa Fe",
        )
        est_cordoba = Establishment(
            name="Merendero El Sol",
            formatted_address="Belgrano 456",
            latitude=-31.4,
            longitude=-64.2,
            place_id=f"place-{uuid.uuid4().hex[:8]}",
            city="Cordoba",
            province="Cordoba",
        )
        responsible = User(
            name="Juan",
            last_name="Gomez",
            email=f"{uuid.uuid4()}@test.com",
            role=ORMUserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )
        author = User(
            name="Sofia",
            last_name="Admin",
            email=f"{uuid.uuid4()}@test.com",
            role=ORMUserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        ana = Subject(
            dni=20000001,
            sex=Sex.FEMALE,
            name="Ana",
            last_name="Alvarez",
            birth_date=date(2015, 3, 14),
            is_rural=False,
            is_indigenous=False,
        )
        beto = Subject(
            dni=20000002,
            sex=Sex.MALE,
            name="Beto",
            last_name="Benitez",
            birth_date=date(2016, 7, 1),
            is_rural=False,
            is_indigenous=False,
        )
        unmeasured = Subject(
            dni=20000003,
            sex=Sex.MALE,
            name="Ceferino",
            last_name="Cruz",
            birth_date=date(2017, 1, 1),
            is_rural=False,
            is_indigenous=False,
        )
        session.add_all(
            [est_rosario, est_cordoba, responsible, author, ana, beto, unmeasured]
        )
        await session.flush()

        session.add_all(
            [
                Measurement(
                    subject_id=ana.id,
                    responsible_id=responsible.id,
                    establishment_id=est_rosario.id,
                    weight_kg=18.5,
                    height_cm=105.25,
                    bmi=bmi_for(18.5, 105.25),
                    measured_at=datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc),
                ),
                Measurement(
                    subject_id=beto.id,
                    responsible_id=responsible.id,
                    establishment_id=est_cordoba.id,
                    weight_kg=22.0,
                    height_cm=112.0,
                    bmi=bmi_for(22.0, 112.0),
                    measured_at=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        survey_active = Survey(
            name="FIES 2026",
            response_target=SurveyResponseTarget.SUBJECT,
            instrument_type=SurveyInstrumentType.FIES,
            created_by_id=author.id,
            is_active=True,
        )
        survey_inactive = Survey(
            name="Encuesta Vieja",
            response_target=SurveyResponseTarget.ANONYMOUS,
            instrument_type=SurveyInstrumentType.CUSTOM,
            created_by_id=author.id,
            is_active=False,
        )
        session.add_all([survey_active, survey_inactive])
        await session.commit()

        return Scenario(
            establishment_rosario=est_rosario.id,
            establishment_cordoba=est_cordoba.id,
            subject_ana=ana.id,
            subject_beto=beto.id,
            subject_unmeasured=unmeasured.id,
            survey_active=survey_active.id,
        )


class TestFileShape:
    """The properties that make the file open cleanly in Excel/Sheets."""

    async def test_content_type_is_csv(self, client, admin_headers, scenario):
        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith("text/csv")

    async def test_starts_with_the_utf8_bom(self, client, admin_headers, scenario):
        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)
        assert response.content.startswith(BOM)

    async def test_accented_names_survive_the_round_trip(
        self, client, admin_headers, scenario
    ):
        response = await client.get(ESTABLISHMENTS_EXPORT_URL, headers=admin_headers)
        assert "Comedor La Unión" in response.content.decode("utf-8-sig")

    async def test_content_disposition_carries_complete_filename(
        self, client, admin_headers, scenario, fixed_export_date
    ):
        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-disposition"] == (
            f'attachment; filename="sujetos_{fixed_export_date.isoformat()}.csv"'
        )

    async def test_numbers_use_a_decimal_comma(self, client, admin_headers, scenario):
        response = await client.get(MEASUREMENTS_EXPORT_URL, headers=admin_headers)
        # Weight is the first column: 18.5 kg must export as 18,50.
        assert "18,50" in response.content.decode("utf-8-sig")

    async def test_dates_use_argentine_order(self, client, admin_headers, scenario):
        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)
        assert "14/03/2015" in response.content.decode("utf-8-sig")


class TestSubjectsExport:
    async def test_exports_current_age_and_elapsed_time(
        self, client, admin_headers, scenario, fixed_export_date
    ):
        response = await client.get(
            SUBJECTS_EXPORT_URL, params={"sex": "female"}, headers=admin_headers
        )
        assert _lines(response) == [
            "Nombre;Documento;Fecha de nacimiento;Edad;Último relevamiento;"
            "Tiempo desde el último relevamiento",
            "Ana Alvarez;20000001;14/03/2015;11 a 5 m;14/03/2026 07:30;hace 5 meses",
        ]

    async def test_respects_a_filter(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_EXPORT_URL, params={"sex": "female"}, headers=admin_headers
        )
        assert _first_cells(response) == ["Ana Alvarez"]

    async def test_respects_the_sort_order(self, client, admin_headers, scenario):
        ascending = await client.get(
            SUBJECTS_EXPORT_URL,
            params={"sort_order": "name_asc"},
            headers=admin_headers,
        )
        descending = await client.get(
            SUBJECTS_EXPORT_URL,
            params={"sort_order": "name_desc"},
            headers=admin_headers,
        )
        assert _first_cells(ascending) == list(reversed(_first_cells(descending)))
        assert _first_cells(ascending)[0] == "Ana Alvarez"

    async def test_never_measured_subject_keeps_blank_timestamp_and_elapsed_placeholder(
        self, client, admin_headers, scenario, fixed_export_date
    ):
        response = await client.get(
            SUBJECTS_EXPORT_URL, params={"search": "Ceferino"}, headers=admin_headers
        )
        assert _data_rows(response) == ["Ceferino Cruz;20000003;01/01/2017;9 a 7 m;;—"]

    async def test_matches_the_listing_endpoint_row_for_row(
        self, client, admin_headers, scenario
    ):
        params = {"sort_order": "name_asc"}
        listing = await client.get(
            "/api/v1/subjects",
            params={**params, "page_size": 100},
            headers=admin_headers,
        )
        export = await client.get(
            SUBJECTS_EXPORT_URL, params=params, headers=admin_headers
        )
        expected = [
            f"{item['name']} {item['last_name']}" for item in listing.json()["items"]
        ]
        assert _first_cells(export) == expected


class TestEstablishmentsExport:
    async def test_respects_a_city_filter(self, client, admin_headers, scenario):
        response = await client.get(
            ESTABLISHMENTS_EXPORT_URL, params={"city": "Rosario"}, headers=admin_headers
        )
        assert _first_cells(response) == ["Comedor La Unión"]

    async def test_respects_the_sort_order(self, client, admin_headers, scenario):
        response = await client.get(
            ESTABLISHMENTS_EXPORT_URL,
            params={"sort_order": "name_asc"},
            headers=admin_headers,
        )
        assert _first_cells(response) == ["Comedor La Unión", "Merendero El Sol"]


class TestMeasurementsExport:
    async def test_exports_every_measurement_when_unfiltered(
        self, client, admin_headers, scenario
    ):
        response = await client.get(MEASUREMENTS_EXPORT_URL, headers=admin_headers)
        assert len(_data_rows(response)) == 2

    async def test_respects_a_province_filter(self, client, admin_headers, scenario):
        response = await client.get(
            MEASUREMENTS_EXPORT_URL,
            params={"province": "Santa Fe"},
            headers=admin_headers,
        )
        assert len(_data_rows(response)) == 1
        assert "Comedor La Unión" in _data_rows(response)[0]

    async def test_respects_the_sort_order(self, client, admin_headers, scenario):
        ascending = await client.get(
            MEASUREMENTS_EXPORT_URL,
            params={"sort_order": "weight_asc"},
            headers=admin_headers,
        )
        descending = await client.get(
            MEASUREMENTS_EXPORT_URL,
            params={"sort_order": "weight_desc"},
            headers=admin_headers,
        )
        assert _first_cells(ascending) == ["18,50", "22,00"]
        assert _first_cells(descending) == ["22,00", "18,50"]


class TestSurveysExport:
    async def test_exports_every_survey_when_unfiltered(
        self, client, admin_headers, scenario
    ):
        response = await client.get(SURVEYS_EXPORT_URL, headers=admin_headers)
        assert len(_data_rows(response)) == 2

    async def test_respects_an_is_active_filter(self, client, admin_headers, scenario):
        response = await client.get(
            SURVEYS_EXPORT_URL, params={"is_active": "true"}, headers=admin_headers
        )
        assert _first_cells(response) == ["FIES 2026"]

    async def test_enum_columns_are_rendered_in_spanish(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            SURVEYS_EXPORT_URL, params={"is_active": "true"}, headers=admin_headers
        )
        assert _data_rows(response)[0].startswith("FIES 2026;Sujeto;Activa;0;")


class TestEstablishmentSubjectsExport:
    def _url(self, establishment_id) -> str:
        return ESTABLISHMENT_SUBJECTS_EXPORT_URL.format(id=establishment_id)

    async def test_age_remains_at_the_measurement_date(
        self, client, admin_headers, scenario, fixed_export_date
    ):
        response = await client.get(
            self._url(scenario.establishment_rosario), headers=admin_headers
        )
        assert _lines(response)[0] == (
            "Nombre;Documento;Edad;Último relevamiento;Peso (kg);Talla (cm);IMC;Estado"
        )
        assert _data_rows(response)[0].startswith(
            "Ana Alvarez;20000001;11a 0m;14/03/2026 07:30;"
        )

    async def test_only_exports_subjects_of_that_establishment(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            self._url(scenario.establishment_rosario), headers=admin_headers
        )
        assert _first_cells(response) == ["Ana Alvarez"]

    async def test_respects_the_search_filter(self, client, admin_headers, scenario):
        response = await client.get(
            self._url(scenario.establishment_rosario),
            params={"search": "nadie"},
            headers=admin_headers,
        )
        assert _data_rows(response) == []


class TestEmptyResult:
    """A filter matching nothing is a successful export with no data rows."""

    @pytest.mark.parametrize(
        "url,params",
        [
            (SUBJECTS_EXPORT_URL, {"search": "nadie-existe"}),
            (ESTABLISHMENTS_EXPORT_URL, {"city": "Narnia"}),
            (MEASUREMENTS_EXPORT_URL, {"province": "Narnia"}),
            (SURVEYS_EXPORT_URL, {"search": "no-existe"}),
        ],
    )
    async def test_returns_200_with_only_the_header_line(
        self, client, admin_headers, scenario, url, params
    ):
        response = await client.get(url, params=params, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        assert len(_lines(response)) == 1
        assert _data_rows(response) == []


class TestUnpaginated:
    async def test_exports_past_the_listing_page_size_cap(
        self, client, admin_headers, app
    ):
        """page_size is capped at 100; an export must ignore that entirely."""
        from app.db.database import AsyncSessionLocal
        from app.domain.subject import Sex
        from app.models.subjects.subject import Subject

        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    Subject(
                        dni=40000000 + i,
                        sex=Sex.MALE,
                        name=f"Sujeto{i:03d}",
                        last_name="Masivo",
                        birth_date=date(2015, 1, 1),
                        is_rural=False,
                        is_indigenous=False,
                    )
                    for i in range(150)
                ]
            )
            await session.commit()

        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)
        assert len(_data_rows(response)) == 150


class TestAuthorization:
    ALL_URLS = [
        SUBJECTS_EXPORT_URL,
        ESTABLISHMENTS_EXPORT_URL,
        MEASUREMENTS_EXPORT_URL,
        SURVEYS_EXPORT_URL,
    ]

    @pytest.mark.parametrize("url", ALL_URLS)
    async def test_analyst_is_allowed(self, client, analyst_headers, scenario, url):
        response = await client.get(url, headers=analyst_headers)
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.parametrize("url", ALL_URLS)
    async def test_field_worker_is_forbidden(
        self, client, field_worker_headers, scenario, url
    ):
        response = await client.get(url, headers=field_worker_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize("url", ALL_URLS)
    async def test_anonymous_is_unauthorized(self, client, scenario, url):
        response = await client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_establishment_export_is_not_public_like_its_listing(
        self, client, scenario
    ):
        # GET /establishments is public; exporting the whole catalogue is not.
        listing = await client.get("/api/v1/establishments")
        assert listing.status_code == status.HTTP_200_OK
        export = await client.get(ESTABLISHMENTS_EXPORT_URL)
        assert export.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_establishment_subjects_export_forbids_field_workers(
        self, client, field_worker_headers, scenario
    ):
        response = await client.get(
            ESTABLISHMENT_SUBJECTS_EXPORT_URL.format(id=scenario.establishment_rosario),
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestStreamingContract:
    """Properties that only exist because the export streams."""

    async def test_declares_the_row_count(self, client, admin_headers, scenario):
        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)

        assert response.headers["x-export-row-count"] == "3"
        assert len(_data_rows(response)) == 3

    async def test_row_count_tracks_the_filter(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_EXPORT_URL, params={"sex": "female"}, headers=admin_headers
        )

        assert response.headers["x-export-row-count"] == "1"
        assert len(_data_rows(response)) == 1

    async def test_row_count_is_zero_for_an_empty_export(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            SUBJECTS_EXPORT_URL, params={"search": "nadie"}, headers=admin_headers
        )

        assert response.headers["x-export-row-count"] == "0"
        assert _data_rows(response) == []
        assert _lines(response) == [
            "Nombre;Documento;Fecha de nacimiento;Edad;Último relevamiento;"
            "Tiempo desde el último relevamiento"
        ]

    async def test_is_chunked_not_content_length(self, client, admin_headers, scenario):
        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)
        # A streamed body has no up-front length; that is what lets an abrupt
        # close be detectable as truncation.
        assert "content-length" not in response.headers

    async def test_session_survives_an_export_spanning_many_chunks(
        self, client, admin_headers, app
    ):
        """The failure the UoW redesign exists to prevent: the request-scoped
        session closing before the body is produced."""
        from app.db.database import AsyncSessionLocal
        from app.domain.subject import Sex
        from app.models.subjects.subject import Subject

        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    Subject(
                        dni=70000000 + i,
                        sex=Sex.MALE,
                        name=f"Largo{i:04d}",
                        last_name="Stream",
                        birth_date=date(2015, 1, 1),
                        is_rural=False,
                        is_indigenous=False,
                    )
                    for i in range(2500)
                ]
            )
            await session.commit()

        response = await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["x-export-row-count"] == "2500"
        assert len(_data_rows(response)) == 2500

    async def test_row_count_matches_the_lines_for_every_endpoint(
        self, client, admin_headers, scenario
    ):
        # The header is only useful if it can be compared to parsed lines, which
        # requires that no cell ever carries a newline.
        for url in (
            SUBJECTS_EXPORT_URL,
            ESTABLISHMENTS_EXPORT_URL,
            MEASUREMENTS_EXPORT_URL,
            SURVEYS_EXPORT_URL,
        ):
            response = await client.get(url, headers=admin_headers)
            declared = int(response.headers["x-export-row-count"])
            assert len(_data_rows(response)) == declared, url


class TestPreflightOrdering:
    """Everything that can fail predictably must fail before the first byte."""

    async def test_unknown_establishment_is_a_real_404(self, client, admin_headers):
        response = await client.get(
            ESTABLISHMENT_SUBJECTS_EXPORT_URL.format(id=uuid.uuid4()),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["title"] == "Establishment not found"

    async def test_inverted_range_is_a_real_400(self, client, admin_headers, scenario):
        response = await client.get(
            MEASUREMENTS_EXPORT_URL,
            params={"measured_from": "2026-06-01", "measured_to": "2026-01-01"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.headers["content-type"].startswith("application/problem+json")

    async def test_forbidden_is_a_real_403(
        self, client, field_worker_headers, scenario
    ):
        response = await client.get(SUBJECTS_EXPORT_URL, headers=field_worker_headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.headers["content-type"].startswith("application/problem+json")


class TestMidStreamFailure:
    async def test_a_failure_mid_body_never_completes_normally(
        self, client, admin_headers, scenario, monkeypatch
    ):
        """A failure after headers must not resolve into a clean, short file.

        Scope note: the in-process ASGI transport re-raises the app exception,
        so this pins the server-side half only -- that the export genuinely
        fails rather than quietly ending the stream. The client-visible half
        (an aborted connection, so ``fetch``/``httpx`` errors on read) is a
        property of the real server and is covered by
        ``test_real_server_aborts_the_connection_on_mid_stream_failure``.
        """
        from app.services.exporters.csv.csv_exporter import CsvExporter

        original = CsvExporter.stream

        def exploding(self, rows):
            async def gen():
                async for chunk in original(self, rows):
                    yield chunk
                    raise RuntimeError("boom mid-stream")

            return gen()

        monkeypatch.setattr(CsvExporter, "stream", exploding)

        with pytest.raises(RuntimeError, match="boom mid-stream"):
            await client.get(SUBJECTS_EXPORT_URL, headers=admin_headers)
