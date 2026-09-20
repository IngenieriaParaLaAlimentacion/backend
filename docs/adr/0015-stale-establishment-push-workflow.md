# ADR-0015: Stale-establishment push notification workflow

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Backend team
- **Related**: ADR-0014 (materialized food stock)

## Context

The notification workflow runs hourly and must preserve pending deliveries across process
restarts, perform FCM requests outside database transactions, and retry transient provider
failures. Its workload is bounded and currently modest, so a dedicated queueing system and worker
fleet would add operational complexity without a proportional benefit.

## Decision

### Run the schedule inside the FastAPI process

FastAPI lifespan starts an APScheduler `AsyncIOScheduler`. It runs the workflow hourly during the
configured active window and shuts down with the application.

The backend is already a persistent process, so an embedded scheduler avoids a separate Railway
Cron Service, an internal HTTP trigger and secret, or another always-running worker. Schedule
misfires do not lose business work because due timestamps and outstanding deliveries are stored in
PostgreSQL rather than only in scheduler memory. Railway bills cron executions for the compute
resources they consume; using the backend process that is already running also avoids that
additional scheduled-service usage.

### Use PostgreSQL as the durable workflow store

The workflow stores two kinds of durable state alongside normal application data:

- one current inactivity cycle per establishment; and
- delivery jobs representing FCM work that has not reached a terminal outcome.

Creating delivery jobs and advancing an inactivity cycle happen in one database transaction.
Delivery jobs are claimed and committed before calling FCM, so provider latency never holds the
business transaction open. If a process stops after claiming work, the lease eventually expires
and a later run can recover it.

This uses infrastructure the application already operates and keeps workflow state close to the
outflows, establishments, users, and devices that determine it.

### Deliver in bounded asynchronous waves

Each run claims only a small wave of immediately runnable jobs, commits their leases, releases the
database connection, and sends that wave concurrently through one reusable HTTP client. It
finalizes the results before claiming another wave and stops after a fixed per-run limit.

This bounds provider concurrency, memory use, database pressure, and scheduler runtime while still
avoiding slow one-device-at-a-time delivery. Claiming only work that can start immediately also
keeps the delivery lease aligned with the actual network operation.

### Accept at-least-once delivery

FCM delivery and PostgreSQL job finalization cannot be committed atomically. A process can stop
after FCM accepts a message but before its delivery job is finalized, allowing a later retry to
send a duplicate.

A transactional outbox, message broker, and dedicated worker would provide stronger decoupling,
independent scaling, and more mature delivery tooling. It would not by itself guarantee exactly-once
push delivery: a worker can still stop after sending to FCM but before acknowledging the message,
unless the provider supports an idempotency mechanism. That additional architecture is not
justified by the expected scale of this application.

The workflow therefore promises at-least-once processing. Durable leases recover abandoned work,
and stable FCM collapse identifiers reduce the user-visible effect of a duplicate where the
platform supports collapsing.

## Consequences

*Positives*

- Scheduled delivery survives application restarts because business progress is stored in
  PostgreSQL.
- FCM calls happen without an open business transaction or a database connection reserved for the
  duration of the network request.
- No Redis, RabbitMQ, queue framework, cron endpoint, or separate worker deployment is required.
- Bounded concurrency improves delivery time without allowing the scheduler to consume unbounded
  application resources.
- The workflow can retry temporary provider failures without recreating reminders from scratch.

*Negatives*

- The API process also owns a background-work lifecycle and must remain running for the in-memory
  schedule to fire.
- Scaling or changing the API process topology also creates additional scheduler instances; the
  database workflow must remain safe when executions overlap.
- PostgreSQL is responsible for a small amount of queue-like work in addition to application data.
- A duplicate notification remains possible in the unavoidable gap between FCM acceptance and
  database finalization.
- Graceful application shutdown may wait for an active bounded delivery wave to finish.

## Alternatives considered

**Send directly from the scheduled pass without durable delivery jobs** — rejected. Advancing the
cycle before sending can lose notifications after a crash; advancing it after every send can repeat
already successful devices when one provider call fails. Durable per-device work makes recovery
explicit.

**Railway Cron Service calling an internal HTTP endpoint** — rejected. It adds a remotely callable
administrative route, secret management, request timeout behavior, and another deployment
configuration for a schedule the persistent backend can own directly.

**A one-shot Railway Cron command** — rejected for now. It isolates scheduling from the API but adds
a second service configuration, deployment lifecycle, and metered compute while each scheduled
execution runs. The current workload does not justify that separation, and the durable database
state already handles missed in-memory schedule ticks.

**A dedicated worker with Redis, RabbitMQ, Celery, or another queue framework** — rejected as
premature. Those systems provide greater throughput and richer retry tooling, but add a broker,
worker lifecycle, monitoring, and another failure domain for one bounded hourly workflow.

**PostgreSQL `pg_cron` or a database queue extension** — rejected. It depends on environment-specific
extensions and still requires application code to call FCM, while the embedded application
scheduler works consistently in local and hosted environments.

**Exactly-once delivery** — rejected as unavailable across PostgreSQL and FCM without provider
support for a transactional idempotency key. Database constraints can prevent duplicate logical
jobs, but cannot prove that FCM did or did not accept a request when the process loses the response.
