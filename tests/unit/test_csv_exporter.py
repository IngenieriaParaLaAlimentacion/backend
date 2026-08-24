from dataclasses import dataclass
from datetime import date

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

    def test_header_order_matches_the_spec(self):
        assert _exporter().headers == ("Nombre", "Monto")

    def test_empty_rows_still_emit_the_header_line(self):
        # An export that matched nothing is a successful export with no data
        # rows -- the file must still open.
        assert _text(_exporter().export([])) == "Nombre;Monto\r\n"

    def test_one_line_per_row(self):
        file_bytes = _exporter().export([_Row("Ana", "1"), _Row("Beto", "2")])
        assert _text(file_bytes).count("\r\n") == 3  # header + 2 rows

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


class TestFilename:
    def test_carries_entity_and_export_date(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.exporters.csv.csv_exporter.today_in_argentina",
            lambda: date(2026, 8, 24),
        )
        assert _exporter("mediciones").filename() == "mediciones_2026-08-24.csv"

    def test_scope_is_slugged_into_the_middle(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.exporters.csv.csv_exporter.today_in_argentina",
            lambda: date(2026, 8, 24),
        )
        filename = _exporter("sujetos").filename(scope="Comedor La Unión")
        assert filename == "sujetos_comedor-la-union_2026-08-24.csv"

    def test_scope_that_slugs_to_nothing_is_dropped(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.exporters.csv.csv_exporter.today_in_argentina",
            lambda: date(2026, 8, 24),
        )
        assert _exporter().filename(scope="!!!") == "sujetos_2026-08-24.csv"


class TestSlugify:
    def test_strips_accents_and_lowercases(self):
        assert slugify("Comedor La Unión") == "comedor-la-union"

    def test_collapses_punctuation_and_trims_edges(self):
        assert slugify("  ¡Merendero #3!  ") == "merendero-3"
