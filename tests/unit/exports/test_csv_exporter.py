import tracemalloc
from dataclasses import dataclass
from datetime import date

import pytest

from app.services.exporters.csv.csv_exporter import CsvColumn, CsvExporter, slugify

BOM = b"\xef\xbb\xbf"


@dataclass
class _Row:
    name: str
    amount: str


def _exporter(entity_name: str = "sujetos") -> CsvExporter[_Row]:
    return CsvExporter(
        (
            CsvColumn("Nombre", lambda r: r.name),
            CsvColumn("Monto", lambda r: r.amount),
        ),
        entity_name=entity_name,
    )


def _text(file_bytes: bytes) -> str:
    """Decode an exported file, dropping the BOM."""
    return file_bytes.decode("utf-8-sig")


class TestCsvExporter:
    def test_content_type_and_extension(self):
        exporter = _exporter()
        assert exporter.file_extension == "csv"
        assert exporter.content_type.startswith("text/csv")

    def test_starts_with_utf8_bom(self):
        # Without the BOM, Excel reads accented characters as mojibake.
        file_bytes = _exporter().export([_Row("Ñandú", "1")])
        assert file_bytes.startswith(BOM)

    def test_uses_semicolon_delimiter_and_crlf(self):
        file_bytes = _exporter().export([_Row("Ana", "18,52")])
        assert _text(file_bytes) == "Nombre;Monto\r\nAna;18,52\r\n"

    def test_empty_rows_still_emit_the_header_line(self):
        # An export that matched nothing is a successful export with no data
        # rows -- the file must still open.
        assert _text(_exporter().export([])) == "Nombre;Monto\r\n"

    def test_quotes_values_containing_the_delimiter(self):
        file_bytes = _exporter().export([_Row("Pérez; Ana", "1")])
        assert '"Pérez; Ana";1' in _text(file_bytes)

    def test_quotes_values_containing_a_quote(self):
        file_bytes = _exporter().export([_Row('Ana "La Flaca"', "1")])
        assert '"Ana ""La Flaca""";1' in _text(file_bytes)

    def test_accepts_a_generator(self):
        # Services stream domain objects in rather than building a list.
        rows = (_Row(str(i), str(i)) for i in range(3))
        assert _text(_exporter().export(rows)).count("\r\n") == 4


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(
        "app.services.exporters.csv.csv_exporter.today_in_argentina",
        lambda: date(2026, 8, 24),
    )


class TestFilename:
    def test_carries_entity_and_export_date(self, fixed_today):
        assert _exporter("mediciones").filename() == "mediciones_2026-08-24.csv"

    def test_scope_is_slugged_into_the_middle(self, fixed_today):
        filename = _exporter("sujetos").filename(scope="Comedor La Unión")
        assert filename == "sujetos_comedor-la-union_2026-08-24.csv"

    def test_scope_that_slugs_to_nothing_is_dropped(self, fixed_today):
        assert _exporter().filename(scope="!!!") == "sujetos_2026-08-24.csv"


class TestSlugify:
    def test_strips_accents_and_lowercases(self):
        assert slugify("Comedor La Unión") == "comedor-la-union"

    def test_collapses_punctuation_and_trims_edges(self):
        assert slugify("  ¡Merendero #3!  ") == "merendero-3"


async def _aiter(rows):
    for row in rows:
        yield row


async def _drain(chunks) -> bytes:
    return b"".join([chunk async for chunk in chunks])


class TestStream:
    @pytest.mark.parametrize("n", [0, 1, 3, 5000])
    async def test_streamed_bytes_equal_buffered_bytes(self, n):
        """The guarantee the whole migration rests on: streaming changed when
        bytes are handed back, not what they are."""
        rows = [_Row(f"Ana Ñ{i}", f"{i},50") for i in range(n)]
        exporter = _exporter()

        assert await _drain(exporter.stream(_aiter(rows))) == exporter.export(rows)

    async def test_empty_stream_still_emits_the_header(self):
        data = await _drain(_exporter().stream(_aiter([])))
        assert _text(data) == "Nombre;Monto\r\n"
        assert data.startswith(BOM)

    async def test_bom_appears_once_on_the_first_chunk_only(self):
        # Enough text to cross the chunk threshold several times over.
        rows = [_Row(f"Nombre largo numero {i}", f"{i},50") for i in range(20_000)]
        chunks = [c async for c in _exporter().stream(_aiter(rows))]

        assert len(chunks) > 1  # genuinely chunked, not one blob
        assert chunks[0].startswith(BOM)
        assert not any(c.startswith(BOM) for c in chunks[1:])
        assert b"".join(chunks).count(BOM) == 1

    async def test_memory_stays_flat_as_rows_grow(self):
        """The point of the exercise: peak must not scale with row count."""

        async def rows(n):
            for i in range(n):
                yield _Row(f"Ana Ñ{i}", f"{i},50")

        peaks = {}
        for n in (1_000, 200_000):
            tracemalloc.start()
            base = tracemalloc.get_traced_memory()[0]
            async for _ in _exporter().stream(rows(n)):
                pass
            peaks[n] = tracemalloc.get_traced_memory()[1] - base
            tracemalloc.stop()

        # 200x the rows must not mean anything like 200x the memory.
        assert peaks[200_000] < peaks[1_000] * 5
        assert peaks[200_000] < 5_000_000  # and stays in single-digit MB
