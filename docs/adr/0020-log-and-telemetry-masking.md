# ADR-0020: Masking of sensitive data in logs and telemetry

- **Status**: Accepted
- **Date**: 2026-10-12
- **Last revised**: 2026-10-15
- **Deciders**: Backend team
- **Related**: Issue #175 (Enmascarado de datos sensibles en logs y telemetría), ADR-0019 (rate limiting; its logs carry paths and header names only)

## Context

The backend sends observability data through three independent paths: stdout, OpenTelemetry logs and
OpenTelemetry spans. The platform handles personal identifiers, data about minors and health values,
and some of it can reach those paths without any log statement being written for it:

- `uvicorn.access` prints the raw query string, and the subject and user listings take a free-text
  `search` that can hold a name, an email or an exact DNI.
- The span attribute `http.url` carries the decoded query string.
- A SQLAlchemy `DBAPIError` message includes the statement parameters, and an asyncpg error includes a
  `DETAIL:` line with the offending value (for example `Key (dni)=(...) already exists`). Both reach
  stdout through the traceback and OpenTelemetry through `exception.*` attributes.
- Library loggers (aiosmtplib, apscheduler, httpx) can carry email addresses in messages and
  exception arguments.

Production has no OpenTelemetry backend today, so its only sink is stdout. Railway, a third party,
collects and stores that output, which makes it a place where personal data must not end up. A
development backend exists and a hosted one may be evaluated later. If telemetry ever leaves the
Railway project, what the backend emits is the last line of defense.

Health data of children and adolescents is sensitive data under Ley 25.326 de Protección de los Datos
Personales (art. 2, "datos sensibles": information about health), and the same law requires the
controller to adopt the security measures needed to avoid its unauthorized disclosure. That is
why the design favors masking too much over masking too little.

The structlog `ProcessorFormatter` has two behaviors that shape the design. Records created with
structlog run the processor chain before they are wrapped, so a processor there changes both the
stdout line and the body the OpenTelemetry handler receives. Records from libraries skip that chain
at emit time: stdout applies it on a copy inside the formatter, while the OpenTelemetry handler
receives the original record with its message, arguments and `exc_info`.

## Decision

Masking is done inside the backend, always on (also in development), driven by constants in the code.
There are no environment variables and no settings: the rules are a security control, so changing
them goes through a pull request and its tests.

### Architecture

The package `app/config/log_masking/` has three layers:

| Module | Responsibility |
| --- | --- |
| `rules.py` | What is masked: key fragments, exact keys, name keys, email keys and query parameter names. Data only, no logic. |
| `core.py` | How it is masked: key normalization, compiled regular expressions and pure functions. It imports nothing from structlog, OpenTelemetry or FastAPI. |
| `adapters.py` | Where it is applied: the structlog processor, the OpenTelemetry log record processor and the span hook. Each one only calls the core. |

`__init__.py` re-exports the public API (`REDACTED`, `MASKING_ERROR`, `mask_email`, `mask_text`,
`mask_query_string`, `mask_event_dict`, `mask_structlog_event`, `MaskingLogRecordProcessor`,
`server_request_hook`), so callers import from `app.config.log_masking`.

### What is masked

Key-based masking over log event dicts, recursive over nested dicts, lists and tuples, returning new
objects (inputs are never mutated). Recursion stops at depth 20, where non-string values are replaced.
The marker is `[REDACTED]`.

Keys are normalized before comparing: lowercase, without `_`, `-` and `.`, so `X-Internal-Token`,
`lastName`, `DNI` and `user.email` match like their plain forms. For each key the decision is, in
order:

1. **Email key** (the normalized key contains `email`): a string value is masked partially
   (`j***@domain.com`, the team's decision); any other value is replaced by `[REDACTED]`.
2. **Exact key or key fragment**: the value is replaced by `[REDACTED]`.
3. **`name` or `nombre`** with another sensitive key in the same dict: the value is replaced by
   `[REDACTED]`. Alone, these keys name establishments, surveys or foods and are kept.
4. **Anything else**: the key is kept and its value is cleaned recursively.

The value is then handled by its type. Numbers, booleans, `None` and UUIDs pass through. Strings are
masked as text (below), and dicts, lists and tuples recursively (a namedtuple comes out as a plain
tuple). Any other type (exceptions, bytes, sets, plain objects) is replaced by its masked `str()`, since
that is the text the renderers would write for it; only the text patterns apply to it, so a sensitive
key inside such an object is not recognized.

What `rules.py` holds:

| Group | Match | Entries |
| --- | --- | --- |
| Key fragments | the normalized key contains it | Identity: `dni`, `cuil`, `cuit`, `documento`, `apellido`, `lastname`, `firstname`, `fullname`, `email`, `phone`, `telefono`, `celular`, `address`, `direccion`, `domicilio`, `birth`, `nacimiento`. Health: `weight`, `peso`, `height`, `talla`, `hemoglob`, `zscore`, `percentil`. Secrets: `password`, `secret`, `apikey`, `privatekey`, `databaseurl`, `redisurl`, `token`, `authorization`, `jwt`, `sessionid`, `setcookie`. |
| Exact keys | the normalized key equals it | `cookie`, `installation_id`, `requester_name`, `bmi`, `avg_bmi`, `imc`, `sex`, `is_indigenous`, `score_fies`, `detail`, `device_name`, `locality`, `answers`, `payload`, `description`, `comments`, `reason` |

`sex`, `is_indigenous` and `score_fies` are sensitive data under art. 2 of Ley 25.326 (ethnic origin and
health). `detail` is the text of a measurement alert, which carries the measured BMI, and `device_name`
often carries the name of its owner. `locality` is the location of a user.

A test walks every column of the schema and fails unless the column is a primary key, a foreign key, a
timestamp, masked by these rules or listed on purpose as not sensitive. Adding a column therefore forces
a decision about whether it is masked.

Fragments match by containment, so they also catch keys nobody meant: `client_address` contains
`address`, and `token` also hides counters such as `prompt_tokens` or `max_tokens`. `authorization`
as a fragment is what covers `proxy-authorization`. That is accepted: a missed key leaks personal data, an extra one only hides a debugging
value. A short word that also appears inside unrelated words goes in the exact keys instead (`bmi`
would match `submitted_by`).

Text values with no key (library messages, tracebacks, the access log line) are masked by content,
in this order:

1. credentials in URL userinfo;
2. `Bearer` tokens;
3. JWT-shaped strings;
4. SQLAlchemy `[parameters: ...]` blocks;
5. PostgreSQL `DETAIL:` lines;
6. values of sensitive query-string parameters (the parameter name stays: `search=[REDACTED]`), where
   a parameter is sensitive if it matches a key fragment, an exact key, `name`, `nombre`, `search` or `q`,
   or if its URL-decoded value has the shape of an email, JWT, CUIL, IPv4 or DNI whatever its name
   (`filter=30123456`, `ref=juan%40mail.com`). Decoding is only used to detect the shape; the same rule
   applies to the access log line and to the span URL, so a new parameter does not need an entry first;
7. emails (partially);
8. CUIL with hyphens (`20-30123456-7`);
9. IPv4 addresses with an optional port;
10. DNI: 7 or 8 digits, or the dotted form (`30.123.456`).

CUIL and IPv4 run before DNI so the DNI pattern does not consume their digit groups.

**The DNI pattern masks too much on purpose.** Any standalone number of 7 or 8 digits inside text is
masked, whether or not it is a document: a byte count, a duration in milliseconds, a compact date. The cost of
a false positive is a hidden debugging value; the cost of a miss is the document of a child or a
guardian in a log kept by a third party. The pattern is bounded so it does not cut into larger
identifiers. A match cannot touch a letter, digit or hyphen on either side, and cannot be part of a
dotted number (a decimal, a version). So:

- Trace ids (hexadecimal) and UUIDs are kept: their digit runs touch letters or hyphens. A UUID segment
  made only of digits is still kept because of the hyphens.
- Numbers longer than 8 digits are kept, as are ISO dates (`2024-01-01`) and timestamps with
  fractional seconds. Compact dates (`20240101`) are masked.
- A period at the end of a sentence does not prevent a match (`DNI 30123456.` is masked).

The rule applies only to text: a numeric value (`int` or `float`) is never inspected, so a DNI logged as
a number under a non-sensitive key is not masked. Database ids are UUIDs in every model, so they are
not affected by the 7-to-8-digit rule. Logs keep ids, trace id, level, route and status code.

### Where it is applied

1. **structlog processor** (`mask_structlog_event`), last in `shared_processors` (after
   `ExceptionRenderer`, so the rendered `exception` is masked). The list feeds both the structlog
   chain and `foreign_pre_chain`, so it covers structlog events on stdout and in the OpenTelemetry
   body, and library records on stdout.
2. **OpenTelemetry `LogRecordProcessor`** (`MaskingLogRecordProcessor`) registered on the
   `LoggerProvider` before the batch processor. Per the OpenTelemetry Logs SDK specification a
   processor may modify the record in `OnEmit` and processors run in registration order. It masks
   body and attributes, including the `exception.*` attributes the handler rebuilds from `exc_info`,
   and is the only place that covers library records on the OpenTelemetry path.
3. **`server_request_hook`** on `FastAPIInstrumentor`, which masks `http.url`, `url.full`,
   `http.target` and `url.query` on the server span (including credentials in the URL userinfo)
   from the raw ASGI query string. A path-only `http.target` stays path-only. It also replaces the
   client address attributes (`net.peer.ip`, `client.address`, `net.sock.peer.addr`) by
   `[REDACTED]`, so the IP is masked in text and in span attributes. Telling clients apart to detect
   abuse is the job of rate limiting (ADR-0019), not of telemetry. Polar's backend
   passes a hook with the same name to its FastAPI instrumentation to sanitize the same attributes
   ([`http_telemetry.py`](https://github.com/polarsource/polar/blob/3b3040adc55b8c52eacccabf6d71d7b7a6348e7e/server/polar/observability/http_telemetry.py));
   it is stricter, since it drops the whole query and replaces the path with the route template.
4. **`hide_parameters=True`** on the SQLAlchemy engine, so error messages do not include parameter
   values.
5. The seed scripts use `setup_logging()` (without the OpenTelemetry handler) instead of
   `logging.basicConfig`, so they get the same masking.

Two call sites were also changed: the Gemini client no longer logs the model response text, and the
SMTP-disabled log shows the recipient masked.

API response bodies are not touched: the processors only see log events and span attributes.

### Failure behavior

The three adapters fail closed and never raise. If the core raises:

- the structlog processor returns `{"event": "[masking error]", "level": <original level>,
  "masking_error": <exception type name>}` (plus the `_record` and `_from_structlog` keys that
  `ProcessorFormatter` deletes right after the chain and needs in order not to drop the line);
- the log record processor sets the body to `[masking error]` and replaces the attributes with
  `{"masking_error": <exception type name>}`;
- the span hook sets the URL attributes (`http.url`, `url.full`, `http.target`, `url.query`) and the
  client address attributes to `[masking error]`.

The adapters do not log the failure, to avoid recursion through the same handlers. Only the exception
type name is kept, never its message, because the type carries no event data and tells which rule
change broke the masking. The hook must not
raise because an exception inside an instrumentation hook can turn the response into a 500
([opentelemetry-python-contrib#3642](https://github.com/open-telemetry/opentelemetry-python-contrib/issues/3642)).

### Conditions of this decision

**HTTP header capture in the instrumentation must stay disabled** (the
`OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*` variables are not set, which is the default). Behind
Railway the socket address is the proxy's, and the real client address travels in the `x-real-ip` and
`X-Client-IP` headers (ADR-0019). If those headers were captured, the instrumentation would add them to
the server span as `http.request.header.*` attributes, and the span hook would not mask them: it only
replaces the fixed list of URL and client address attributes named above. Enabling header capture
therefore requires extending that list first, with a test against the real `FastAPIInstrumentor`.

### What is not covered (stated explicitly)

- **Exception events and the status description inside spans are not masked.** The Python SDK has no
  hook that is both supported and able to edit them: `SpanProcessor.on_start` runs before the data
  exists and `_on_ending` runs after the SDK has made the span attributes immutable (SDK 1.44.0). The
  planned follow-up is the Collector `redaction` and `transform` processors, once a telemetry
  destination is chosen.
- **Residual risk:** PostgreSQL `DETAIL` text (`Key (dni)=(...) already exists`) can still reach span
  exception events. `hide_parameters` hides SQLAlchemy parameters only, not the driver `DETAIL` text.
- **Values with no recognizable shape under a non-sensitive key.** A first name inside a message, or
  under a key with no sensitive sibling, is not masked. Documents other than 7 to 8 digit DNIs, a CUIL
  written without hyphens and IPv6 addresses are not recognized either, and neither is a number
  (`int` or `float`) under a non-sensitive key.
- Out of scope: cost and volume reduction, the choice of telemetry destination, and moving the
  `search` filter out of the query string (it would change the contract with the backoffice and mobile
  app).

## Consequences

*Positives*

- The known sensitive keys and the values with a recognizable shape (emails, credentials, tokens,
  CUIL, IPs, DNIs, database parameters and `DETAIL` lines) do not reach stdout or OpenTelemetry logs
  through app code, library logs or database errors, and URLs in spans do not carry sensitive query
  values.
- Works with whatever destination is chosen later, and with none (production writes only to stdout).
- The rules are one data file (`rules.py`), the logic is pure and testable without structlog or
  OpenTelemetry, and the adapters are thin.
- Library logs are covered without touching their loggers.
- If masking breaks, nothing unmasked is passed on.

*Negatives*

- Over-masking is part of the design: fragments hide unrelated keys that contain them, standalone
  numbers of 7 to 8 digits in text are masked even when they are not documents, IPs are masked inside URLs
  (including internal addresses in `url.full`) and a non-string value under a key containing `email` is
  fully masked.
- Masked logs are harder to debug: a `description`, `reason` or `payload` shows only `[REDACTED]`, and
  when masking fails the content of that line is lost.
- A sensitive value in a non-sensitive key, or inside free text without a recognizable shape, is not
  masked. The rules are maintained by hand and must grow with the schema; the schema coverage test
  fails when a new column is neither masked nor listed as not sensitive.
- The span exception gap above stays open until a Collector is in place.
- The OpenTelemetry processor depends on the (still underscore-named) logs SDK API: records are
  mutated in place and `BoundedAttributes` is replaced by a plain dict, which drops the
  dropped-attributes counter. The wiring is pinned by tests and has to be rechecked on upgrades.
- Every log line is scanned by a set of regular expressions.

## Standards and patterns

| Reference | How it applies |
| --- | --- |
| [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) | Sensitive data is removed or masked before it is written, and the masking happens in the logging pipeline and not at each call site. |
| [NIST SP 800-122](https://csrc.nist.gov/pubs/sp/800/122/final) (protecting PII) | Minimization and de-identification of PII: identifiers and health values are replaced before they leave the process. |
| Data minimization and privacy by design (GDPR arts. 5(1)(c) and 25 as reference; Ley 25.326) | Only what is needed to operate (ids, trace id, route, status) is kept in observability data, and masking is on by default. |
| Fail-safe defaults (Saltzer and Schroeder) | The adapters fail closed: on error the data is replaced by `[masking error]` instead of being passed on. |
| Defense in depth | Layers: call sites that avoid logging sensitive values, masking in process, and, as a planned complement, the Collector. |
| Ports and adapters (hexagonal architecture) | A pure core (`core.py`) with thin adapters per integration point (`adapters.py`) and the rules apart (`rules.py`). |
| OpenTelemetry [handling sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/) and the Collector [redaction processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/redactionprocessor) | The guidance to sanitize in the SDK or in the Collector; the redaction processor is the planned complement for span exception events. |

**Honest note:** the design is a denylist (known keys and known shapes are masked, the rest passes).
OWASP in general prefers allowlists. For logs that is a pragmatic concession, because an allowlist of
every key and message would block free-form library logs and make logs hard to use. The allowlist
(`allowed_keys` of the Collector redaction processor) remains a planned complement.

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
installed SDK. The `server_request_hook` runs at the right moment on the mutable server span.

**Masking at the call sites only** — rejected as the main measure. The leaks listed in the context
are implicit (access log, SQL errors, library messages), so call-site cleanup would miss them.

**Making masking configurable per environment** — rejected. A switch that is off somewhere is the
configuration that ships by mistake; the debugging cost is paid with ids and trace ids instead.

**Rules in an external file (YAML) or extra keys through an environment variable** — rejected. The
rules are a security control and must go through a pull request and its tests. A missing or invalid
file, or an unset variable, could also leave the masking running with no rules, which is the failure
the design is meant to avoid.
