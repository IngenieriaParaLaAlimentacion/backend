"""Shared HTTP plumbing for the listing CSV export endpoints.

Exports stream: the body is produced after the handler has returned, so two
things follow that shape everything here.

**The session cannot come from a dependency.** FastAPI closes a dependency
generator when the *handler* returns, which for a streamed response is before
the first row is read. So the streaming generator opens and owns its own
``UnitOfWork`` for the whole body — see ``csv_stream_response``. The shared
providers in ``app.core.dependencies`` are deliberately left alone.

**Anything that can fail predictably must fail first.** Validation, the 404 for
an unknown establishment and the row count run in a pre-flight phase, on a
normal request-scoped session, before the response starts. Once bytes are on
the wire the status is already 200 and an error can only truncate the file.
"""

from collections.abc import AsyncIterator, Callable

from fastapi import status
from fastapi.responses import StreamingResponse

from app.api.v1.params import AUTH_RESPONSES
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.db.unit_of_work import UnitOfWork
from app.services.exporters.csv.csv_exporter import CsvExporter

#: Header naming how many data rows the file should carry. A client that counts
#: fewer has a truncated download -- see docs/frontend/csv-exports.md.
ROW_COUNT_HEADER = "X-Export-Row-Count"

CSV_EXPORT_RESPONSES: dict[int | str, dict] = {
    **AUTH_RESPONSES,
    status.HTTP_200_OK: {
        "description": (
            "Listing exported successfully as a CSV file, streamed. "
            f"`{ROW_COUNT_HEADER}` states how many data rows to expect."
        ),
        "content": {"text/csv": {}},
    },
    status.HTTP_400_BAD_REQUEST: {
        "description": "A value in the result set has no export label defined"
    },
}


async def _stream_owning_uow(
    build: Callable[[IUnitOfWork], AsyncIterator[bytes]],
) -> AsyncIterator[bytes]:
    """Run ``build``'s chunks inside a UnitOfWork that lives as long as they do.

    The export's rows arrive from a server-side cursor, so the session and its
    transaction have to stay open for the whole response body — past the point
    where a ``Depends``-provided session would already have been closed.
    """
    async with UnitOfWork() as uow:
        async for chunk in build(uow):
            yield chunk


def csv_stream_response(
    build: Callable[[IUnitOfWork], AsyncIterator[bytes]],
    filename: str,
    row_count: int,
) -> StreamingResponse:
    """Stream an export as a CSV download.

    ``build`` receives a UnitOfWork scoped to the response and returns the
    exporter's chunks. If it raises mid-body the connection is aborted without
    a terminating chunk, which is what lets a client detect the truncation
    rather than silently keeping a partial file.

    Clients reading these headers from JavaScript across origins would need
    them exposed via CORS; this app serves them same-origin.
    """
    return StreamingResponse(
        _stream_owning_uow(build),
        media_type=CsvExporter.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            ROW_COUNT_HEADER: str(row_count),
        },
    )
