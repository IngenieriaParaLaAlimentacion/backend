# Grafana observability

The backend exports its telemetry to Grafana Cloud. The dashboards live in the
[Grafana folder](https://agusgermi.grafana.net/dashboards/f/fv6pvr/raiz) and are
also kept here as JSON so they can be recreated.

| File | Panels |
|---|---|
| `http-overview.dashboard.json` | p95 latency per endpoint, 5xx error rate, throughput (requests/s) |
| `logs-overview.dashboard.json` | Lines/s, counts by level, log volume, logs by logger, last errors and warnings, live logs with text search (Loki) |

## What is exported and where

Everything is sent over OTLP/HTTP (protobuf) to the Grafana Cloud OTLP gateway,
configured in `app/config/telemetry.py`. The exporters read the standard
`OTEL_EXPORTER_OTLP_*` variables, so the code holds no endpoint or credential.

| Signal | What it contains | Grafana Cloud store |
|---|---|---|
| Metrics | HTTP server metrics from the FastAPI instrumentation, exported every 60 s (SDK default) | Prometheus (`grafanacloud-<stack>-prom`) |
| Logs | Python logs from the app, `uvicorn` and `fastapi` | Loki (`grafanacloud-<stack>-logs`) |
| Traces | One server span per request, `/health` and `/ready` excluded | Tempo |

All signals share the same resource attributes:

| Resource attribute | Source |
|---|---|
| `service.name` | `SERVICE_NAME` (`backend-prod`, `backend-dev` on Railway) |
| `service.environment` | `ENVIRONMENT` |

Logs are also written to stdout, as JSON outside `development` and as colored
console output in `development`. Railway collects that output; it is independent of
the OTLP export.

Sensitive values are masked **before** they leave the process, on both paths
(stdout and OTLP). The rules are in [ADR-0023](../adr/0023-log-and-telemetry-masking.md).

## Log structure

Each log line carries the same fields on stdout and in OTLP.

| Field | Description |
|---|---|
| `event` | The log message |
| `level` | `debug`, `info`, `warning`, `error`, `critical` |
| `logger` | Name of the logger that emitted it (module path) |
| `timestamp` | ISO 8601 |
| `filename`, `func_name`, `lineno` | Call site |
| `service_name` | Same value as the `service.name` resource attribute |
| `trace_id`, `span_id` | Present only inside an active request span, so they let you jump from a log to its trace |
| `exception` | Rendered traceback, present when an exception was logged |
| any bound key | Context bound with structlog (`contextvars`) or passed as keyword arguments |

Values under sensitive keys appear as `[REDACTED]`.

```json
{
  "event": "request completed",
  "level": "info",
  "logger": "app.services.example",
  "timestamp": "2026-10-24T14:03:11.482913Z",
  "filename": "example.py",
  "func_name": "create",
  "lineno": 42,
  "service_name": "backend-prod",
  "trace_id": "5b8efff798038103d269b633813fc60c",
  "span_id": "eee19b7ec3c1b174"
}
```

Records from libraries (`uvicorn.access`, `httpx`, `apscheduler`) are not created
with structlog, so on the OTLP path their body is the plain message string.

### How Loki indexes them

The logs dashboard relies on these:

| Loki field | Origin | Used for |
|---|---|---|
| `service_name` (label) | resource attribute `service.name` | the **Service** dropdown |
| `detected_level` | derived by Loki from the OTLP severity | counts and filters by level |
| `scope_name` | logger that emitted the record | the "Logs by source" panel |

Example queries:

```logql
# Errors of one service
{service_name="backend-prod"} | detected_level=~"(?i)error|critical|fatal"

# Text search
{service_name="backend-prod"} |~ "(?i)timeout"
```

## Dashboard variables

The **Service** dropdown lists `backend-prod` and `backend-dev`, matching the
`SERVICE_NAME` set on each Railway environment. Add any new service name to the
variable's custom list.

The logs panels reference the Loki data source by name (`grafanacloud-agusgermi-logs`).
When importing into another stack, replace that name in the JSON with the target
Loki data source name.

## Required backend configuration

| Variable | Value | Why |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Grafana Cloud OTLP gateway URL | Where telemetry is sent |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Protocol the gateway expects |
| `OTEL_EXPORTER_OTLP_HEADERS` | `Authorization=Basic%20<token>` | Grafana Cloud credentials |
| `OTEL_SEMCONV_STABILITY_OPT_IN` | `http` | Stable HTTP metric names, see below |
| `SERVICE_NAME` | `backend-prod` / `backend-dev` | Value of the `service_name` label and the **Service** dropdown |

The HTTP panels query the server duration histogram under the stable OpenTelemetry
HTTP semantic conventions (`http_server_request_duration_seconds_*`, labels
`http_route`, `http_request_method`, `http_response_status_code`). Without
`OTEL_SEMCONV_STABILITY_OPT_IN=http` the instrumentation emits the legacy
`http_server_duration_milliseconds_*` metric, which carries the raw path
(`http_target`) and no `http_route`.

## Import

1. In Grafana Cloud: *Dashboards → New → Import*.
2. Upload `http-overview.dashboard.json` or `logs-overview.dashboard.json`.
3. For the HTTP dashboard, pick the Prometheus data source
   (`grafanacloud-<stack>-prom`) and the service (the value of `SERVICE_NAME`,
   shown as the `job` label). The logs dashboard needs no prompt; check the Loki
   data source name as described above.

## Update

Edit the dashboard in Grafana, then *Export → Export as JSON* and replace the file
in this directory.
