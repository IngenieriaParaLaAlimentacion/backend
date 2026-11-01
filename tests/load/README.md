# Load tests

k6 scripts that measure how each flow of the API performs under load. The first goal is an approximate baseline per flow, not a pass/fail budget. A flow only fails on broken checks, or on thresholds it declares itself.

## How it fits together

```
 runner: where k6 runs                       target: what gets measured
 ┌──────────────────────────┐    BASE_URL     ┌──────────────────────────────┐
 │ your machine             │ ──────────────▶ │ local backend                │
 │   — or —                 │                 │   — or —                     │
 │ GitHub Actions           │  DATABASE_URL   │ Railway development          │
 │                          │ ──────────────▶ │ (API + Postgres TCP proxy)   │
 │ tests/load/run.sh        │                 │                              │
 └──────────────────────────┘                 └──────────────────────────────┘
```

The runner and the target are independent. Only `BASE_URL` and `DATABASE_URL` pick the target, so both must point at the same deployment. The runner always runs in the container built from `tests/load/Dockerfile`, both locally and in CI.

Every run of `tests/load/run.sh` does the same steps:

1. Waits until `$BASE_URL/ready` answers.
2. **Seeds** the load-test dataset (`python -m tests.load.data.seed`). The first time against a database it loads everything: 10 establishments, 12 users and 2,000 subjects with 3 measurements each. After that it sees the data is there and skips.
3. **Cleans** what an earlier run left, in case one stopped halfway (`python -m tests.load.data.cleanup`).
4. Runs the flows in `tests/load/flows/` one at a time. `all` runs `smoke` first and skips the rest if it fails.
5. Writes the results to `tests/load/results/`.
6. **Cleans** what this run wrote. This step runs even when a flow fails.

Exit codes: `0` everything passed, `1` a flow failed, `2` missing configuration or an unknown flow.

## Configuration

| Variable | What it is |
|---|---|
| `BASE_URL` | Base URL of the backend under test, without a trailing slash |
| `DATABASE_URL` | URL of that backend's Postgres, for the seed and the cleanup. `postgresql://` works as is |
| `LOAD_TEST_PASSWORD` | Password of every load-test user. The seed sets it the first time it runs against a database, so later runs against that database must use the same one |
| `TARGET_REVISION` | Optional. The commit deployed on the target, recorded in `run.json` |
| `STEPS` | Optional. Concurrent users at each step, comma separated. Default `5,10,25,50` |
| `STEP_DURATION` | Optional. How long each step lasts, as `30s` or `2m`. Default `2m` |

The variables come from the shell or from `tests/load/.env`, which is gitignored. Start from `tests/load/.env.example`.

## Running locally

Prerequisites: Docker with Compose v2.

```bash
# 1. Backend config, if you don't have one yet
cp .env.example .env

# 2. Start the target: Postgres, Redis, migrations + base seeds, backend on :8080
docker compose up -d --build --wait

# 3. Runner config; the defaults point at the backend from step 2
cp tests/load/.env.example tests/load/.env

# 4. Run: all flows, or one by name (a file in tests/load/flows/ without .js)
docker compose -f tests/load/compose.yml run --rm --build runner all
docker compose -f tests/load/compose.yml run --rm --build runner smoke

# 5. Look at the results
cat tests/load/results/summary.md

# 6. Stop the target (-v also drops the local database and its load-test data)
docker compose down
```

`--build` rebuilds the runner image, so changes to the flows are picked up; the scripts are baked into the image. Inside the container, `host.docker.internal` is the host machine on macOS and Linux alike.

To point a local run at another target, such as Railway development, change `BASE_URL` and `DATABASE_URL` in `tests/load/.env`, or export them before step 4.

## Running from GitHub Actions

`.github/workflows/load-tests.yml` builds the same runner image, with a GitHub Actions cache, and runs the same compose command against Railway development.

Run it from Actions → *Load tests* → *Run workflow*, with `flow` set to `all` or a flow name. A manual workflow only appears in the Actions tab once the file is on the repository's default branch.

Runs queue and never overlap, because two runs against the single replica would skew each other's numbers.

### One-time setup

**Railway (development environment)**

1. On the Postgres service, turn on the **TCP proxy** (Settings → Networking). Its public host and port go in `LOAD_TEST_DATABASE_URL`.
2. Recommended: create a role for the load tests instead of using the default superuser. It can read and write rows, but can't change the schema:

   ```sql
   CREATE ROLE loadtest LOGIN PASSWORD '<a strong password>';
   GRANT CONNECT ON DATABASE railway TO loadtest;
   GRANT USAGE ON SCHEMA public TO loadtest;
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO loadtest;
   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO loadtest;
   -- So tables added by later migrations are covered too
   ALTER DEFAULT PRIVILEGES IN SCHEMA public
     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO loadtest;
   ```

   Run the `ALTER DEFAULT PRIVILEGES` as the role that runs the migrations, so it applies to the tables that role creates.

**GitHub**

1. Settings → Environments → **New environment** `load-tests`. Optionally, require a reviewer or limit it to `develop` and `main`.
2. In that environment, add:

   | Kind | Name | Value |
   |---|---|---|
   | Variable | `LOAD_TEST_BASE_URL` | Public URL of the development backend |
   | Secret | `LOAD_TEST_DATABASE_URL` | `postgresql://loadtest:<password>@<proxy host>:<proxy port>/railway` |
   | Secret | `LOAD_TEST_PASSWORD` | Any strong password; it becomes the load-test users' password on the first seed |

   With the CLI, so the values never show in the terminal history:

   ```bash
   gh variable set LOAD_TEST_BASE_URL --env load-tests
   gh secret set LOAD_TEST_DATABASE_URL --env load-tests
   gh secret set LOAD_TEST_PASSWORD --env load-tests
   ```

## Flows

| Flow | What it does | Logs in as |
|---|---|---|
| `smoke` | Checks the backend is ready, a load-test user logs in and a listing answers. Runs first | a field worker |
| `listings` | GETs random pages of establishments, subjects and measurements | the analyst |
| `subject_sync` | POST `/subjects` with ids made on the device | the 10 field workers |
| `measurement_sync` | POST `/measurements` for seeded subjects of the worker's establishment | the 10 field workers |
| `food_intake_sync` | POST `/food-intakes` with 3 catalog foods, to the worker's establishment | the 10 field workers |
| `survey_response_sync` | POST responses to the `LOADTEST` FIES survey | the 10 field workers |

Every flow except smoke runs the same stepped profile: one step per value of `STEPS`, one after another, each holding that many VUs for `STEP_DURATION`. A step starts 5 s after the previous one ends, once its last requests have finished, so two steps never overlap. With the defaults, a flow takes about 8 minutes plus about 30 s of logins. The VUs send requests back to back, with no pause, so each step shows the most the backend serves at that concurrency.

In the sync flows, 20% of the writes resend a record the VU already sent, as a worker does when a sync is retried. The `replays → 200` column is the share that came back as the idempotent 200.

For a quick run, shorten the profile:

```bash
STEPS=2,5 STEP_DURATION=15s docker compose -f tests/load/compose.yml run --rm --build runner all
```

## Results

| Where | What |
|---|---|
| Job summary (CI) | `summary.md`, shown at the top of the workflow run |
| Artifact `load-test-results` (CI, kept 30 days) | The whole `tests/load/results/` folder |
| `tests/load/results/` (local) | Same files, overwritten by each run |

Files:

- `summary.md`: every flow's table, in run order, each followed by its passed and failed checks
- `<flow>.md`: one flow's table, written by its `handleSummary`
- `run.json`: when the run finished, `base_url`, `target_revision`, the flows run and the ones that failed

k6 doesn't see the replica's CPU and memory. Read them from Railway's metrics for the run's time window.

After a run that passed, the workflow's `report` job gives Claude the results, [`REPORT_PROMPT.md`](REPORT_PROMPT.md) and [`baseline.md`](baseline.md), and adds the report to the job summary and to a `load-test-report` artifact. Claude only sees the results and the prompt: the base URL is removed from `run.json`, and nothing names where the API runs. The job uses the repository's `CLAUDE_CODE_OAUTH_TOKEN` secret, the one `claude.yml` uses, and a failure in it never fails the run. The same prompt works by hand with any AI and the contents of `tests/load/results/`.

`baseline.md` is the reviewed report of the run the team compares against, so each report says what changed since then. Replace it when a new run becomes the reference, after checking its numbers against that run's `load-test-results` artifact.

## The load-test data

The dataset lives in `tests/load/data/dataset.py`. Its volume is set by the constants at the top of the file. Every record it creates carries the marker `LOADTEST` in a text field:

| Entity | Field | Example |
|---|---|---|
| Users | `email`, `last_name` | `loadtest.relevador01@tpp.com`, `LOADTEST` |
| Establishments | `name`, `place_id` | `LOADTEST Comedor 01`, `reference-loadtest_01` |
| Subjects | `last_name`, DNI from 80,000,001 up | `LOADTEST Gómez` |
| Survey | `name` | `LOADTEST Encuesta FIES` |

The flows write the same marker in what they create.

The cleanup only removes rows tied to the load-test establishments and users, and keeps the seeded ones, all in one transaction. Each run starts from the same data, so runs can be compared. Removing the whole dataset by hand starts from the same marker. The cleanup is the reference for the order, because some foreign keys restrict deletes.

## Test of the cleanup

`tests/load/tests/` checks that the cleanup removes a run's writes and nothing else, since it deletes rows on a shared database. Its fixture runs the seed, so the seed is covered too. The app's suites never collect them, because `testpaths` only lists `tests/unit` and `tests/integration`. Run them by path (Docker must be running, as for the integration tests):

```bash
poetry run pytest tests/load/tests
```

The workflow runs them in its `data-tests` job before any load run. Their fixtures come from `tests/integration/conftest.py`.

## Adding a flow

1. Create `tests/load/flows/<name>.js`. It reads `__ENV.BASE_URL` and `__ENV.LOAD_TEST_PASSWORD`.
2. Log in once in `setup()` and share the tokens. Login is limited to 5/min per email and 20/min per IP, and every request from a runner comes from one IP. Access tokens last 15 minutes, so keep a flow shorter than that.
3. Write `LOADTEST` in any record the flow creates, and only write to the load-test establishments.
4. Write the flow's table to `tests/load/results/<name>.md` from `handleSummary`. `run.sh` collects it into `summary.md`.
5. Add `thresholds` only when a budget is decided for that flow.

`tests/load/flows/smoke.js` is the smallest example.
