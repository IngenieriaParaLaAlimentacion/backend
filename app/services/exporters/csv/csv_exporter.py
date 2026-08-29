"""A generic, column-spec-driven CSV exporter for the listing views.

Unlike ``SurveyResponseExporter`` (ADR-0005), whose contract is a survey plus
its responses, a listing export is plain tabular data: a sequence of domain
objects and an ordered set of columns. One ``CsvExporter`` instance per view
binds those columns once, so services stay unaware of headers and layout and
the HTTP layer only needs ``content_type``/``file_extension``. See ADR-0009.
"""

import codecs
import csv
import io
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from app.utils.dates import today_in_argentina

T = TypeVar("T")

# Excel on a Spanish locale splits on ';', not ',', and needs the BOM to read
# accented characters as UTF-8 on a double-click. CRLF is the RFC 4180 default
# it expects. Together these make the file open cleanly without an import
# wizard, which is the whole point of the export.
_DELIMITER = ";"
_LINE_TERMINATOR = "\r\n"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Reduce a name to a filename-safe ASCII slug.

    Accents are decomposed and dropped rather than transliterated, so
    "Comedor La Unión" becomes "comedor-la-union".
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")


@dataclass(frozen=True)
class CsvColumn(Generic[T]):
    """One column of an exported listing.

    ``header`` must match the column name shown in the UI table, and the order
    of a view's columns must match the table's — that is what makes the export
    recognisable as "what I was looking at".
    """

    header: str
    value: Callable[[T], str]


class CsvExporter(Generic[T]):
    """Renders rows of ``T`` as a CSV file, per its bound column spec."""

    content_type = "text/csv; charset=utf-8"
    file_extension = "csv"

    def __init__(self, columns: Sequence[CsvColumn[T]], entity_name: str) -> None:
        self._columns = tuple(columns)
        self._entity_name = entity_name

    @property
    def headers(self) -> tuple[str, ...]:
        """The column headers, in export order."""
        return tuple(column.header for column in self._columns)

    def export(self, rows: Iterable[T]) -> bytes:
        """Return the CSV's raw bytes for these rows.

        The header line is always written, so an empty result set still yields
        a valid file the client can open — an export that matched nothing is a
        successful export with no data rows, not an error.
        """
        buffer = io.StringIO()
        writer = csv.writer(
            buffer,
            delimiter=_DELIMITER,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator=_LINE_TERMINATOR,
        )
        writer.writerow(self.headers)
        for row in rows:
            writer.writerow([column.value(row) for column in self._columns])
        return codecs.BOM_UTF8 + buffer.getvalue().encode("utf-8")

    def filename(self, scope: str | None = None) -> str:
        """Build the download filename, e.g. ``mediciones_2026-08-24.csv``.

        ``scope`` names what the export was narrowed to — an establishment, for
        the per-establishment subject listing — and is slugified into the
        middle of the name: ``sujetos_comedor-la-union_2026-08-24.csv``.
        """
        parts = [self._entity_name]
        if scope:
            slug = slugify(scope)
            if slug:
                parts.append(slug)
        parts.append(today_in_argentina().isoformat())
        return f"{'_'.join(parts)}.{self.file_extension}"
