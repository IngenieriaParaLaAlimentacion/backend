import logging

import structlog

from app.config.log_masking import MASKING_ERROR, REDACTED, adapters


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
        '[REDACTED] - "GET /api/v1/subjects?search=[REDACTED]&page=2 HTTP/1.1" 200'
    )


def test_structlog_event_reaches_otel_masked(stdout_logs, otel_logs):
    structlog.get_logger("app").info("saved", dni="12345678", weight_kg=18.2)

    (exported,) = otel_logs.exporter.records
    assert "12345678" not in str(exported.body)
    assert "18.2" not in str(exported.body)


def _raise(*args, **kwargs):
    raise RuntimeError("masking broke")


def test_stdout_line_is_replaced_when_masking_fails(stdout_logs, monkeypatch):
    monkeypatch.setattr(adapters, "mask_event_dict", _raise)
    structlog.get_logger("app").warning("saved", dni="30123456")
    logging.getLogger("aiosmtplib").warning("sent to %s", "ana@dominio.com")

    lines = stdout_logs()
    assert [line["event"] for line in lines] == [MASKING_ERROR, MASKING_ERROR]
    assert [line["level"] for line in lines] == ["warning", "warning"]
    assert "30123456" not in str(lines)
    assert "ana@dominio.com" not in str(lines)
