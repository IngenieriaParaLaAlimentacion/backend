"""Shared HTTP plumbing for the listing CSV export endpoints.

Every export handler returns the same shape of response — raw bytes, the
exporter's own content type, and an attachment filename — so the header and
the OpenAPI block are declared once here instead of in each router.
"""

from fastapi import Response, status

from app.api.v1.params import AUTH_RESPONSES
from app.services.exporters.csv.csv_exporter import CsvExporter

CSV_EXPORT_RESPONSES: dict[int | str, dict] = {
    **AUTH_RESPONSES,
    status.HTTP_200_OK: {
        "description": "Listing exported successfully as a CSV file",
        "content": {"text/csv": {}},
    },
    status.HTTP_400_BAD_REQUEST: {
        "description": "A value in the result set has no export label defined"
    },
}


def csv_file_response(file_bytes: bytes, filename: str) -> Response:
    """Wrap exported CSV bytes in a download response.

    The bytes are returned whole rather than streamed, matching the existing
    xlsx export. Clients reading the filename from JavaScript across origins
    would additionally need ``Content-Disposition`` exposed via CORS; this app
    serves them same-origin.
    """
    return Response(
        content=file_bytes,
        media_type=CsvExporter.content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
