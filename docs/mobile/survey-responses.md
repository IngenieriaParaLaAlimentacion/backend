# Survey Responses: Mobile Integration Guide

Covers the endpoints shipped in PR #64 (`feature/relevador-encuesta-interview`, Module
2): discovering surveys, submitting a response, viewing responses, editing a response,
and the offline-first sync contract behind all of it.

Related design docs: [ADR-0003](../adr/0003-anonymous-unbounded-survey-responses.md)
(responses are anonymous, individual, unbounded per establishment) and
[ADR-0004](../adr/0004-offline-first-response-sync-via-client-ids.md) (client-generated-id
idempotency — the same pattern already used by `POST /api/v1/subjects`, see
[subjects-offline-sync.md](subjects-offline-sync.md)).

Roles allowed to submit/edit responses: `field_worker`, `admin`, `superadmin`. `analyst`
cannot submit or edit.

---

## 1. Discover surveys to answer

```http
GET /api/v1/surveys/available?page=1&page_size=20
Authorization: Bearer <token>
```

Returns active surveys the caller may respond to: generic surveys, plus targeted
surveys aimed at one of the caller's *approved* establishments (pending/rejected
establishment access does not count — see `_check_establishment_access` in
`app/services/survey_response_service.py`). Field worker, admin, and superadmin only.

Response shape (`SurveyListItem`, paginated — summary only, no questions):

```json
{
  "items": [
    {
      "id": "…",
      "name": "Encuesta FIES",
      "scope": "generic",
      "is_active": true,
      "created_by_id": "…",
      "question_count": 8,
      "created_at": "…"
    }
  ],
  "total": 1, "page": 1, "page_size": 20, "total_pages": 1
}
```

### Fetching the full question set for a survey

```http
GET /api/v1/surveys/{survey_id}
Authorization: Bearer <token>
```

Returns the full `SurveyResponse` shape — ordered `questions`, each with its
`response_type`, `is_required` flag, and `options` (for choice types). This is what the
mobile app needs to render the response form; the answer payload in §2 is keyed by the
`id` of each question/option returned here.

A `field_worker` may fetch:
- any **generic** survey, or
- a **targeted** survey aimed at one of their *approved* establishments (same
  eligibility rule as §1's `/available` listing).

Otherwise `403 Forbidden`. `admin`/`analyst`/`superadmin` can fetch any survey
unrestricted. `404` if the survey id doesn't exist.

## 2. Submit a response — offline-first

```http
POST /api/v1/survey-responses
Authorization: Bearer <token>
Content-Type: application/json

{
  "id": "018f6e2a-7c3a-7e21-9b6a-2b1d3c4e5f60",
  "survey_id": "…",
  "establishment_id": "…",
  "answers": {
    "<question_id_1>": "<option_id>",
    "<question_id_2>": ["<option_id_a>", "<option_id_b>"],
    "<question_id_3>": "free text",
    "<question_id_4>": 3
  },
  "event_at": "2026-07-10T15:30:00Z"
}
```

Same client-generated-id idempotency pattern as subjects/measurements (ADR-0004):

- `id` is optional, but mobile should **always** generate and send a UUID (prefer
  UUIDv7, UUIDv4 is a fine fallback) at the moment the response is completed locally —
  online or offline.
- `event_at` is when the relevador actually finished the interview, client-supplied. It
  may be well before the device reconnects. It cannot be in the future (`422` if it is).
- `answers` keys are question ids (as strings); values depend on the question's
  `response_type`:

| `response_type` | Expected value |
|---|---|
| `single_choice` | one option id (string), must belong to the question |
| `multiple_choice` | list of option ids (strings), every element must be a string and belong to the question |
| `numeric` | int or float |
| `text` | string, opaque |
| `date` | ISO-8601 date string |

- **No draft mode.** Every question where `is_required` is true must have a
  non-empty answer, or the whole submission is rejected (`400`) — there's no
  partial-save/resume-later on the server side. If the mobile UX allows saving
  progress before all required questions are answered, that has to be a purely local
  draft that isn't POSTed until complete.
- **No per-survey uniqueness.** Any number of responses can exist for the same
  `(survey_id, establishment_id)` — this is expected (N interviews per visit), not an
  error case to guard against client-side.

### Response → action

| Response | Meaning | Mobile action |
|---|---|---|
| `201 Created` | New response | Mark synced. |
| `200 OK` | Same `id` already existed (replay) | Mark synced, no-op. |
| `400 Bad Request` | Answers invalid, or establishment outside a `TARGETED` survey's audience | Mark error, surface to user. Do **not** blind-retry — the payload itself needs fixing. |
| `403 Forbidden` | Role can't submit, or field worker lacks *approved* access to the establishment | Mark error, surface to user. Note: this check re-runs even on a replay of an already-synced `id`, checked against the response's establishment — if a field worker's establishment access is revoked *after* a response synced, later retries of that same submission (e.g. a naive retry-all-pending sweep) will start returning `403` even though the response already exists server-side. Don't treat `403` on retry as "never landed." |
| `404 Not Found` | `survey_id` or `establishment_id` doesn't exist | Mark error — likely stale local survey/establishment cache, force a refresh. |
| `401` | Token expired/invalid | Refresh token, retry. |
| `5xx` / network error | Transient | Keep pending, retry with exponential backoff — safe, the id makes retries idempotent. |

All error bodies are RFC 7807 `application/problem+json`.

## 3. View responses

There are two levels: the activity feed (list, summary only) and the response detail
endpoint (single item, full answers).

### List — the activity feed

```http
GET /api/v1/users/me/activity?type=survey_response&page=1&page_size=20
Authorization: Bearer <token>
```

- Returns the **caller's own** activity only (subjects created, measurements taken,
  survey responses submitted), date-descending, paginated. Use `?type=survey_response`
  to filter to just responses; omit `type` to get the mixed feed.
- Accessible to every authenticated role.
- Each item (`SurveyResponseListItem`) is a summary, **not the full answers**:

```json
{
  "type": "survey_response",
  "occurred_at": "2026-07-10T15:30:00Z",
  "survey_response": {
    "id": "…",
    "event_at": "2026-07-10T15:30:00Z",
    "survey": { "id": "…", "name": "Encuesta FIES" },
    "establishment": { "id": "…", "name": "Comedor Sur", "city": "…" }
  }
}
```

### Detail — tapping an activity item

```http
GET /api/v1/survey-responses/{response_id}
Authorization: Bearer <token>
```

Returns the full `SurveyResponseResponse` — same shape as the `submit`/`edit` response
body, including `answers`:

```json
{
  "id": "…",
  "survey_id": "…",
  "establishment_id": "…",
  "submitted_by_id": "…",
  "answers": { "<question_id>": "<option_id>", "...": "..." },
  "event_at": "2026-07-10T15:30:00Z",
  "created_at": "…",
  "updated_at": "…"
}
```

- Restricted to the **original submitter** or an `admin`/`superadmin` — the same actors
  allowed to edit it (§4). A `field_worker` viewing someone else's response gets `403`.
  `analyst` gets `403` unconditionally (analysts never submit/edit responses).
- `404` if the response id doesn't exist.
- Use this to pre-fill the edit form: `GET` the current answers, let the user modify
  them, then `PUT` the full replacement per §4. This also covers cross-device editing —
  a device that never submitted the response can now fetch its current state before
  editing, instead of relying on a local cache of what some other device sent.

## 4. Edit a response

```http
PUT /api/v1/survey-responses/{response_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "id": "<fresh-uuid-per-edit-attempt>",
  "answers": { "...": "..." },
  "event_at": "2026-07-10T16:00:00Z"
}
```

- Restricted to the original submitter, or an `admin`/`superadmin` (any editor role,
  regardless of who submitted).
- **Full replace**: send the complete answer set, not a diff.
- **`id` here identifies the edit attempt, not the response** — it's a *separate*
  idempotency key from the response's own `id`. Generate a **fresh UUID per edit
  attempt** (not the response's id, not a reused edit id). Retrying the same edit
  attempt (same `id`) after a network failure is safe and no-ops. **Reusing the
  response's own `id` as the edit's `id`, or reusing one edit's `id` for a later edit,
  will not error — it will simply fail to apply, because the server can't distinguish
  it from an already-applied edit.** This is the one place client-side discipline
  actually matters (ADR-0004's stated risk).
- **Conflict resolution is last-write-wins by `event_at`, not sync order.** If two
  edits to the same response happen offline on different devices before either syncs,
  both edit attempts are recorded, but only the one with the more recent `event_at`
  ends up as the response's current `answers`. No `409`, no merge UI — if the edit with
  the earlier `event_at` syncs *after* the one with the later `event_at`, it is
  recorded but does **not** become current. There's no API-visible signal that this
  happened; the only place to see all edit attempts is the (currently
  API-inaccessible) `survey_response_edits` audit table.

### Response → action

| Response | Meaning | Mobile action |
|---|---|---|
| `200 OK` | Edit applied (or replayed) | Mark synced. Note: the returned body reflects the response's **current** state, which — per last-write-wins above — may not equal the edit you just sent if a later-`event_at` edit already won. |
| `400 Bad Request` | Answers invalid | Mark error, surface to user, don't blind-retry. |
| `403 Forbidden` | Not the submitter and not admin/superadmin | Mark error, surface to user. |
| `404 Not Found` | `response_id` doesn't exist | Mark error — stale local id, likely never actually synced; check whether the original submission actually landed. |
| `401` | Token expired/invalid | Refresh, retry. |
| `5xx` / network error | Transient | Keep pending, retry — safe. |

## 5. Offline-first sync ordering

Same rule as subjects (see [subjects-offline-sync.md](subjects-offline-sync.md)) plus
one addition specific to responses:

1. Sync surveys/establishments (read-only reference data) before responses that
   reference them.
2. Sync a response's `submit` before any `edit` against it — an edit for a
   not-yet-synced response will `404`.
3. If multiple edits to the same response were made offline, sync them in any order —
   correctness depends on each edit's `event_at`, not on arrival order (§4) — but keep
   each edit's own retry loop independent so one edit's failure doesn't block others
   from a different response.

## 6. Local sync state machine

```text
PENDING ──▶ SYNCING ──▶ SYNCED
                   └──▶ ERROR (400/403/404 — needs user or data fix, don't auto-retry)
```

Both submit and edit are safe to retry from `PENDING`/network-failure indefinitely —
the client-generated id makes every retry idempotent (§2, §4).
