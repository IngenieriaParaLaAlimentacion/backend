import logging

import structlog

from app.config.log_masking import REDACTED


def test_structlog_event_is_masked_on_stdout(stdout_logs):
    structlog.get_logger("app").info(
        "login for juan@dominio.com",
        email="juan@dominio.com",
        dni="12345678",
        details={"password": "s3cret", "subject_id": "7d9f"},
    )

    (line,) = stdout_logs()
    assert line["event"] == "login for j***@dominio.com"
    assert line["email"] == "j***@dominio.com"
    assert line["dni"] == REDACTED
    assert line["details"] == {"password": REDACTED, "subject_id": "7d9f"}
    assert line["level"] == "info"
    assert line["logger"] == "app"


def test_structlog_exception_text_is_masked_on_stdout(stdout_logs):
    try:
        raise ValueError("DETAIL:  Key (dni)=(12345678) already exists")
    except ValueError:
        structlog.get_logger("app").exception("insert failed")

    (line,) = stdout_logs()
    assert "12345678" not in line["exception"]
    assert "ValueError" in line["exception"]


def test_library_record_with_exc_info_is_masked_on_stdout(stdout_logs):
    try:
        raise OSError("refused for ana@dominio.com")
    except OSError:
        logging.getLogger("aiosmtplib").exception("delivery to bob@dominio.com failed")

    (line,) = stdout_logs()
    assert line["event"] == "delivery to b***@dominio.com failed"
    assert "ana@dominio.com" not in line["exception"]


def test_uvicorn_access_line_masks_query_values_on_stdout(stdout_logs):
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "190.1.2.3:5000",
        "GET",
        "/api/v1/subjects?search=12345678&page=2",
        "1.1",
        200,
    )

    (line,) = stdout_logs()
    assert line["event"] == (
        '190.1.2.3:5000 - "GET /api/v1/subjects?search=[REDACTED]&page=2 HTTP/1.1" 200'
    )


def test_structlog_event_reaches_otel_masked(stdout_logs, otel_logs):
    structlog.get_logger("app").info("saved", dni="12345678", weight_kg=18.2)

    (exported,) = otel_logs.exporter.records
    assert "12345678" not in str(exported.body)
    assert "18.2" not in str(exported.body)


def test_library_record_reaches_otel_masked(stdout_logs, otel_logs):
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "190.1.2.3:5", "GET", "/s?search=Juan", "1.1", 200
    )

    (exported,) = otel_logs.exporter.records
    assert "Juan" not in exported.body
