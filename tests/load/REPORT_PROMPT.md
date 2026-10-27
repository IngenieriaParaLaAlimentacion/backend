# Prompt for the load-test report

Give this text to an AI together with the `load-test-results` zip from the workflow run (or the contents of `tests/load/results/` after a local run). Fill in the fields in `<angle brackets>` first; leave a field as "unknown" rather than guessing.

---

You are a performance engineer. Write a report on a load-test run of a REST API, using only the files attached and the context below. Every number you give must come from those files or from this prompt; when something cannot be concluded from them, say so instead of estimating.

Write the report in <language, e.g. Spanish (Argentina)>, for <audience, e.g. the development team and a non-technical project lead>.

## The system under test

- REST API for a nutrition and food-security platform used by community kitchens in Argentina. Field workers use a mobile app that works offline and syncs when it gets signal back: each sync is a series of idempotent POSTs, keyed by an id generated on the device, so resending a record returns `200` with the stored record instead of creating a duplicate (`201`).
- Python 3.11, FastAPI, async SQLAlchemy with asyncpg, PostgreSQL.
- Deployed on Railway as a single replica with no autoscaling. Plan and replica size: <Railway plan, vCPU and RAM of the backend service>. Database: <Railway Postgres plan or size>.
- SQLAlchemy connection pool: <pool size + max overflow, default 5 + 10>.
- Target of this run: <environment, e.g. Railway development>, deployed commit <commit or "unknown">.

## How the test works

- The runner was <GitHub Actions ubuntu-latest | a local machine>, sending every request from a single IP.
- Before the flows, the database holds a fixed seeded dataset: 10 establishments, 10 field workers (one per establishment), 1 analyst, 2,000 subjects with 3 measurements each. Everything a run writes is removed afterwards, so every run starts from the same data.
- Each flow logs its users in once and then runs a stepped profile: one step per value of <STEPS, default 5,10,25,50> concurrent virtual users (VUs), each step held for <STEP_DURATION, default 2m>, back to back.
- VUs send requests back to back with no pause, so a step measures the most the backend served at that concurrency, not the behaviour of N humans with think time.
- Flows:
  - `smoke`: one pass over login and a listing; a gate before the others.
  - `listings`: an analyst GETs random pages (20 items) of establishments, subjects and measurements.
  - `subject_sync`, `measurement_sync`, `food_intake_sync`, `survey_response_sync`: field workers POST new records; 20% of writes resend a record already sent (a "replay"), which must return `200`.

## The attached files

- `summary.md`: one table per flow, one row per step.
- `<flow>.md`: the same table for a single flow.
- `<flow>.json`: k6's full summary data. Per-step values are under `metrics`, in keys such as `http_req_duration{step:025}` (`values` holds `avg`, `p(50)`, `p(95)`, `p(99)`, `max`, in milliseconds), `http_reqs{step:025}` (`count`), `http_req_failed{step:025}` (`rate`), `replay_returned_200{step:025}` (`rate`) and `checks` (`passes`, `fails`). Step tags are zero-padded VU counts. Requests tagged `name: setup` are logins and fixture reads before the load, not part of any step.
- `run.json`: when the run finished, the base URL, the deployed commit if known, the flows run and the ones that failed.

Table columns: `VUs` concurrent users; `req/s` requests per second over the step; `p50`/`p95`/`p99` latency percentiles; `errors` share of responses that were not 2xx/3xx; `replays → 200` share of resent records answered with the idempotent `200`.

## Resource usage during the run (from Railway, not in the files)

- Backend CPU: <peak and typical per step, or "not collected">
- Backend memory: <peak, or "not collected">
- Database CPU / connections: <values, or "not collected">
- Time window of the run: <start – end, with time zone>

## What to write

1. **Summary** (5–8 lines): what was measured, the main finding, and the load at which the single replica stops keeping up, if the data shows one.
2. **Results per flow**: for each flow, its table and two or three sentences on how latency, throughput and errors change from step to step. Point out the step where throughput stops growing while latency keeps rising (saturation), and any step with errors.
3. **Comparison between flows**: which flows are the most and least expensive, in latency and in requests per second at the same concurrency, and what in each flow could explain the difference (e.g. listings with counts over large tables, writes that compute alerts or update counters).
4. **Idempotency**: whether replays always returned `200`, and whether they cost more or less than first writes, if the JSON allows telling them apart (tag `kind:replay` vs `kind:write`).
5. **Capacity**: translate the saturation point into an approximate number of field workers syncing at the same time, stating the assumptions. Remember VUs do not pause, so one VU is more load than one person.
6. **Likely bottlenecks**: hypotheses consistent with the data and the resource usage above, such as the connection pool size, CPU of the single replica, or specific queries. Mark them as hypotheses and say what measurement would confirm each one.
7. **Recommendations**: concrete next steps, ordered by expected impact (e.g. tune the pool, add an index, scale the plan, add a second replica), and the latency/error budget per flow you would propose based on these numbers.
8. **Limitations of this run**: single runner IP, no think time, dataset size versus production, short steps, missing resource metrics, anything in `run.json` marked as failed.
9. **Comparison with a previous run** (only if one is attached): what changed per flow and step, and whether the change is beyond normal run-to-run noise.

Use tables where they help, keep numbers with their units, and round latencies to milliseconds.
