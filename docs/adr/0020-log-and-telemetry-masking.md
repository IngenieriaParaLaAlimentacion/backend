# ADR-0020: Masking of sensitive data in logs and telemetry

- **Status**: Accepted
- **Date**: 2026-10-12
- **Deciders**: Backend team
- **Related**: Issue #175 (Enmascarado de datos sensibles en logs y telemetría), ADR-0019 (rate limiting; its logs carry paths and header names only)

## Context

The backend sends observability data through three independent paths: stdout (collected by Railway),
OpenTelemetry logs and OpenTelemetry spans. None of them masked anything. The platform handles
personal identifiers, data about minors and health values, and some of it reached those paths
without any log statement being written for it:

- `uvicorn.access` prints the raw query string, and the subject and user listings take a free-text
  `search` that can hold a name, an email or an exact DNI.
- The span attribute `http.url` carries the decoded query string.
- A SQLAlchemy `DBAPIError` message includes the statement parameters, and an asyncpg error includes a
  `DETAIL:` line with the offending value (for example `Key (dni)=(...) already exists`). Both reach
  stdout through the traceback and OpenTelemetry through `exception.*` attributes.
- Library loggers (aiosmtplib, apscheduler, httpx) can carry email addresses in messages and
  exception arguments.

Production has no OpenTelemetry backend today, so its only sink is stdout; a development backend
exists and a hosted one may be evaluated later. If telemetry ever leaves the Railway project, what the
backend emits is the last line of defense.

The structlog `ProcessorFormatter` has two behaviors that shape the design. Records created with
structlog run the processor chain before they are wrapped, so a processor there changes both the
stdout line and the body the OpenTelemetry handler receives. Records from libraries skip that chain
at emit time: stdout applies it on a copy inside the formatter, while the OpenTelemetry handler
receives the original record with its message, arguments and `exc_info`.

## Decision

Masking is done inside the backend, always on (also in development), driven by constants in the code
(no environment variables, no new settings). One module, `app/config/log_masking.py`, holds the rules
and three adapters.

### What is masked

Key-based masking over log event dicts, recursive over nested dicts and lists, returning new
objects (inputs are never mutated). The marker is `[REDACTED]`. Keys are compared case-insensitively
ignoring `_` and `-`, so `X-Internal-Token`, `lastName` and `DNI` match.

| Category | Keys |
| --- | --- |
| Credentials and tokens | `password`, `new_password`, `password_hashed`, `access_token`, `refresh_token`, `token`, `token_hash`, `authorization`, `cookie`, `x-internal-token`, `fcm_token`, `installation_id` |
| Settings secrets | `jwt_secret_*`, `gemini_api_key`, `storage_secret_access_key`, `fcm_private_key`, `smtp_password`, `internal_service_token`, `database_url`, `rate_limit_redis_url` |
| Personal identifiers | `dni`, `last_name`, `requester_name`, `requester_last_name`, `contact_phone` |
| Health values | `weight_kg`, `height_cm`, `bmi`, `hemoglobin` (field does not exist yet) |
| Free text and JSON | `answers`, `payload`, `description`, `comments`, `reason` |
| Emails, partially (`j***@domain.com`) | `email`, `requester_email`, `to_email` |

`name` is masked only when the same dict also has `last_name`, `dni` or `email`; elsewhere it names
establishments, surveys or foods. `birth_date` and the client IP are not masked. Logs keep ids, trace
id, level, route and status code.

Text values with no key (library messages, tracebacks, the access log line) are masked by content:
emails (partially), values of sensitive query-string parameters (the parameter name stays:
`search=[REDACTED]`; `page`, `subject_id`, `establishment_id` stay visible), URL credentials,
`Bearer` tokens, JWT-shaped strings, SQLAlchemy `[parameters: ...]` blocks and PostgreSQL `DETAIL:`
lines.

### Where it is applied

1. **structlog processor**, last in `shared_processors` (after `ExceptionRenderer`, so the rendered
   `exception` is masked). The list feeds both the structlog chain and `foreign_pre_chain`, so it
   covers structlog events on stdout and in the OpenTelemetry body, and library records on stdout.
2. **OpenTelemetry `LogRecordProcessor`** registered on the `LoggerProvider` before the batch
   processor. Per the OpenTelemetry Logs SDK specification a processor may modify the record in
   `OnEmit` and processors run in registration order. It masks body and attributes, including the
   `exception.*` attributes the handler rebuilds from `exc_info`, and is the only place that covers
   library records on the OpenTelemetry path.
3. **`server_request_hook`** on `FastAPIInstrumentor`, which masks `http.url`, `url.full` and
   `url.query` on the server span (including credentials in the URL userinfo) from the raw ASGI query
   string. Polar's backend uses the same hook for the same purpose.
4. **`hide_parameters=True`** on the SQLAlchemy engine, so error messages do not include parameter
   values.
5. The seed scripts use `setup_logging()` (without the OpenTelemetry handler) instead of
   `logging.basicConfig`, so they get the same masking, and the super admin email is no longer logged.

API response bodies are not touched: the processors only see log events and span attributes.

### What is not covered (stated explicitly)

- **Exception events and the status description inside spans are not masked in this change.** The
  Python SDK has no hook that is both supported and able to edit them: `SpanProcessor.on_start` runs
  before the data exists and `_on_ending` runs after the SDK has made the span attributes
  immutable (SDK 1.44.0). The planned
  follow-up is the Collector `redaction` and `transform` processors, once a telemetry destination is
  chosen.
- **Residual risk:** PostgreSQL `DETAIL` text (`Key (dni)=(...) already exists`) can still reach span
  exception events. `hide_parameters` hides SQLAlchemy parameters only, not the driver `DETAIL` text.
- **A DNI typed as free text** (8 digits) cannot be detected by a regular expression without
  destroying ids and timestamps; it is covered only by the key and query-parameter name rules.
- Out of scope: cost and volume reduction, the choice of telemetry destination, masking the client
  IP, and moving the `search` filter out of the query string (it would change the contract with the
  backoffice and mobile app).

## Consequences

*Positives*

- No credentials, personal identifiers or health values reach stdout or OpenTelemetry logs through
  app code, library logs or database errors, and URLs in spans do not carry sensitive query values.
- Works with whatever destination is chosen later, and with none (production writes only to stdout).
- One module and one constant list; a new sensitive field is one line.
- Library logs are covered without touching their loggers.

*Negatives*

- A sensitive value in a non-sensitive key, or inside free text without a recognizable shape, is not
  masked. The key list is maintained by hand and must grow with the schema (for example the
  hemoglobin field when Module 3 exists).
- Masked logs are harder to debug: a `description`, `reason` or `payload` shows only `[REDACTED]`.
- The span exception gap above stays open until a Collector is in place.
- The OpenTelemetry processor depends on the (still underscore-named) logs SDK API: records are
  mutated in place and `BoundedAttributes` is replaced by a plain dict, which drops the
  dropped-attributes counter. The wiring is pinned by tests and has to be rechecked on upgrades.
- Every log line is scanned by a handful of regular expressions.

## Alternatives considered

**Collector-only redaction** (`redaction` or `transform` processors) — rejected as the only measure.
Production has no Collector, so stdout would stay unmasked, and any telemetry that leaves the
process would carry the data over the wire. It remains the planned complement for span exception
events.

**A vendor agent with built-in scrubbing (Sentry, Datadog)** — rejected. It adds a vendor and a
data flow to a third party to solve a problem that a few hundred lines solve in process, and it would
not cover stdout.

**`logging.Filter` on the OpenTelemetry handler** — rejected in favour of a `LogRecordProcessor`. A
filter sees the original `LogRecord`, but the handler rebuilds `exception.*` from `exc_info` after the
filter, so the exception text is out of its reach. The processor runs on the translated record, with
body and attributes in one place, and is sanctioned by the specification.

**Wrapping the span exporter** to rewrite exception events — rejected. It works technically, but the
specification defines an exporter as an encoder and transmitter of read-only spans, so rebuilding
spans there goes against its intent and ties the masking to one exporter class. The span exception
gap is left to the Collector instead.

**`SpanProcessor.on_start` / `_on_ending`** — rejected for the span attributes. `on_start` runs before
the URL attributes are set and `_on_ending` runs after the attributes became immutable in the
installed SDK. The
`server_request_hook` runs at the right moment on the mutable server span.

**Masking at the call sites only** — rejected as the main measure. The leaks listed in the context
are implicit (access log, SQL errors, library messages), so call-site cleanup would miss them. Two
call sites were also changed: the Gemini client no longer logs the model response text, and the
SMTP-disabled log shows the recipient masked.

**Making masking configurable per environment** — rejected. A switch that is off somewhere is the
configuration that ships by mistake; the debugging cost is paid with ids and trace ids instead.
