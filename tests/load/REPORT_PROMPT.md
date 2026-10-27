# Prompt for the load-test report

The *Load tests* workflow gives this prompt to Claude after a successful run, together with the run's results. It can also be given by hand to any AI, with the contents of `tests/load/results/`.

---

You are a performance engineer. Write a report on a load-test run of a REST API, using only the files attached and the context below. Every number you give must come from those files; when something cannot be concluded from them, say so instead of estimating. Do not assume anything about where or on what hardware the API runs: that is not part of the files.

Write the report in Spanish (Argentina), for the development team, with a summary a non-technical project lead can follow.

## The system under test

- REST API for a nutrition and food-security platform used by community kitchens in Argentina. Field workers use a mobile app that works offline and syncs when it gets signal back: each sync is a series of idempotent POSTs, keyed by an id generated on the device, so resending a record returns `200` with the stored record instead of creating a duplicate (`201`).
- Python, FastAPI, async SQLAlchemy with asyncpg, PostgreSQL. Unless configured otherwise, the database connection pool holds 5 connections plus 10 overflow.

## How the test works

- Every request comes from one load generator, from a single IP.
- Before the flows, the database holds a fixed seeded dataset: 10 establishments, 10 field workers (one per establishment), 1 analyst, 2,000 subjects with 3 measurements each. Everything a run writes is removed afterwards, so every run starts from the same data.
- Each flow logs its users in once and then runs a stepped profile: one step per concurrency level, each held for the same time, back to back. The levels and the step length are in `profile` in each `<flow>.json` (`steps`, `step_seconds`).
- Virtual users (VUs) send requests back to back with no pause, so a step measures the most the API served at that concurrency, not the behaviour of that many people with think time.
- Flows:
  - `smoke`: one pass over login and a listing; a gate before the others. It has no per-step table.
  - `listings`: an analyst GETs random pages (20 items) of establishments, subjects and measurements.
  - `subject_sync`, `measurement_sync`, `food_intake_sync`, `survey_response_sync`: field workers POST new records; 20% of writes resend a record already sent (a "replay"), which must return `200`.

## The attached files

- `summary.md`: one table per flow, one row per step.
- `<flow>.md`: the same table for a single flow.
- `<flow>.json`: k6's summary data. Per-step values are under `metrics`, in keys such as `http_req_duration{step:025}` (`values` holds `avg`, `p(50)`, `p(95)`, `p(99)`, `max`, in milliseconds), `http_reqs{step:025}` (`count`), `http_req_failed{step:025}` (`rate`) and `replay_returned_200{step:025}` (`rate`). Step tags are zero-padded VU counts. `http_req_duration{kind:write}` and `http_req_duration{kind:replay}` separate first writes from replays over the whole flow. `checks` holds `passes` and `fails`.
- `run.json`: when the run finished, the deployed commit if known, the flows run and the ones that failed.

Table columns: `VUs` concurrent users; `req/s` requests per second over the step; `p50`/`p95`/`p99` latency percentiles; `errors` share of responses that were not 2xx/3xx; `replays → 200` share of resent records answered with the idempotent `200`.

## What to write

1. **Summary** (5–8 lines): what was measured, the main finding, and the concurrency at which the API stops keeping up, if the data shows one.
2. **Results per flow**: for each flow, its table and two or three sentences on how latency, throughput and errors change from step to step. Point out the step where throughput stops growing while latency keeps rising (saturation), and any step with errors.
3. **Comparison between flows**: which flows are the most and least expensive, in latency and in requests per second at the same concurrency, and what in each flow could explain the difference (e.g. listings that count over large tables, writes that compute alerts or update counters).
4. **Idempotency**: whether replays always returned `200`, and how their latency compares with first writes.
5. **Capacity**: translate the saturation point into an approximate number of field workers syncing at the same time, stating the assumptions. Remember VUs do not pause, so one VU is more load than one person.
6. **Likely bottlenecks**: hypotheses consistent with the data, such as the connection pool size or specific queries. Mark them as hypotheses and say what measurement would confirm each one.
7. **Recommendations**: concrete next steps, ordered by expected impact, and the latency/error budget per flow you would propose based on these numbers.
8. **Limitations of this run**: a single load generator, no think time, dataset size, step length, no resource metrics (CPU, memory, database connections) in the files, anything in `run.json` marked as failed.

Use tables where they help, keep numbers with their units, and round latencies to milliseconds.
