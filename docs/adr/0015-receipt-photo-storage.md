# ADR-0015: Receipt photo storage — confirm-time upload to Cloudflare R2

- **Status**: Accepted
- **Date**: 2026-09-13
- **Deciders**: Backend team
- **Related**: ADR-0013 (food intake relational schema — reserved the photo attachment column
  without settling its shape), ADR-0004 (offline-first response sync via client ids — the
  idempotency pattern this ADR's replay guarantee depends on)

## Context

The US this ADR supports lets a user register a food intake by photographing the receipt
instead of typing every line by hand. Three of its acceptance criteria constrain the design:

- **CA 1**: the backend processes the image and proposes food lines; the photo is linked to the
  intake as an attachment (`origen = foto`).
- **CA 2**: the user reviews, corrects and confirms the proposed lines before anything is
  persisted — a photo-loaded intake ends up structurally identical to a manually-loaded one
  (ADR-0013's `food_intakes`/`food_intake_items` tables), differing only in `source`.
- **CA 3**: if the image can't be processed or nothing is detected, the user is told and offered
  manual entry instead — *"sin perder la foto"* (without losing the photo).

`architecture.md` further constrains it: the backend is the only orchestrator of storage and LLM
calls, and object storage is S3-compatible (provider unspecified at the time). ADR-0013 already
reserved a nullable photo-attachment column on `food_intakes` but deliberately left open what kind
of reference it holds and when it gets written.

That leaves three concrete questions this ADR settles: which storage backend and how is it
called from a fully async codebase; **when** does a photo actually get written to storage,
relative to whether the user ever confirms; and how does a confirmation request carry both
structured JSON and a binary file.

## Decision

### Storage backend: Cloudflare R2, behind a generic `IObjectStorage` port

R2 was chosen for this project. It exposes an S3-compatible API, so the standard AWS S3 client
works against it unmodified — only the endpoint URL and region (`"auto"`, R2's required value)
differ from talking to AWS itself. The client is `aioboto3`, not synchronous `boto3`: this
codebase is fully async (FastAPI, `asyncpg`, `aiosmtplib`), and a blocking S3 call inside a
request handler would stall the event loop for every other concurrent request, not just the one
uploading a photo.

`IObjectStorage` (an `ABC`, mirroring how `IUnitOfWork` is already structured) declares exactly
one method, `save(key, content_type, data)`. It knows nothing about receipts or `food_intakes` —
callers own their own key naming. This is deliberate: `architecture.md` lists object storage as
infrastructure shared across modules , so the port and the underlying bucket are reusable without change. `R2ObjectStorage`
is the only implementation today; the interface exists so a unit test never needs real network
access or credentials — it substitutes a fake, the same way UoW-dependent service tests already
substitute a mocked `IUnitOfWork`. A failed save raises `ObjectStorageError`, a plain exception in
the same spirit as `UniqueConstraintError`: the storage layer doesn't know what HTTP status a
failure should produce, so the caller translates it (`ReceiptPhotoStorageError`, `502`).

### Upload timing
>Nothing is written to R2 until confirmation, and only after every check that could still reject it has passed.

This is the central decision, and it overturned the feature's first implementation.

**What was tried first, and rejected:** uploading the photo eagerly, inside
`POST /food-intakes/from-photo`, before the user had reviewed anything. This came from reading CA
3's *"sin perder la foto"* too literally — as if the server had to durably persist the bytes the
instant they arrived, or they were lost. That doesn't hold up: the user's phone still has the
original file regardless of what the backend does with it. Not losing the photo is a UX guarantee
(the user shouldn't have to re-take or re-pick it), not proof the server must write to R2 before a
human has decided anything. Under eager upload, every abandoned flow — the user closes the app,
picks the wrong establishment, changes their mind, or the extraction proposal simply isn't good
enough to bother confirming — left a permanently orphaned object in R2 that nothing in Postgres
ever referenced. Given CA 2 puts a genuine review step between "upload for extraction" and
"confirm", and not every review ends in a confirmation, this was not a rare edge case.

**Final decision:** `POST /food-intakes/from-photo` only validates the image and runs extraction
in memory; it never touches storage. The photo is uploaded solely by
`POST /food-intakes/from-photo/confirm`, and only after, in order:

1. **Idempotency replay check** — if the client-generated `id` already exists, the existing row is
   returned as-is and storage is never touched. A retried confirmation must not upload a second,
   now-orphaned copy of the same photo.
2. **Establishment exists.**
3. **Actor has approved access to it.**

Only once all three pass does the upload happen, immediately followed by
`FoodIntakeService.register(data, actor, photo_key=...)` in the same call. These three checks
duplicate a few lines of `register`'s own preamble on purpose: `register`'s checks run too late for
this purpose, after the point an upload would already have happened.

One narrow, accepted gap remains: a line referencing an unknown `food_id` is still only caught
inside `register`, *after* the photo has been uploaded — this one case can still leave an orphan.
Not eliminated by also duplicating food resolution here, since `food_id`s come from the catalog
(a client bug or data problem, not something a normal user flow produces) rather than free text a
user could plausibly mistype.

**Cost accepted:** the image is uploaded over the network twice per confirmed intake — once to
`/from-photo` for extraction, once again to `/from-photo/confirm` to actually persist it. A
server-side cache holding the bytes between the two calls was considered and rejected: it trades
this problem for a structurally identical one (an unconfirmed cache entry instead of an
unconfirmed R2 object) while adding new infrastructure (a cache plus an expiry policy) that
nothing else in this project needs, for a bandwidth saving judged not worth it at this feature's
scale — a single receipt photo, capped by `receipt_image_max_bytes`, uploaded by a person.

### Two endpoints, not one endpoint with a mode flag

Merging propose and confirm into a single `POST /food-intakes/from-photo` — branching on whether
`items` was included in the payload — was considered and rejected. It would make "does this
request write to the database and update stock" a fact hidden inside a conditional rather than
one visible in the route list. For a system that mutates stock on confirmation, that distinction
should be structural, not dependent on what happened to be in the request body.

`POST /food-intakes/from-photo` never persists. `POST /food-intakes/from-photo/confirm` always
either creates the intake or safely returns the existing one on replay. Both cases the new
endpoint serves — CA 1's success path (`source = photo`) and CA 3's fallback (extraction found
nothing, the user typed the items by hand but keeps the photo, `source = manual`) — go through it,
because it's the only endpoint that knows how to receive a file and persist it.

### Confirm request shape: JSON in a Form field, not flat form fields

`multipart/form-data` has no native way to carry `FoodIntakeRequest`'s nested `items` array. The
confirm endpoint takes a `data` Form field holding the exact JSON body `POST /food-intakes`
accepts, parsed server-side into `FoodIntakeRequest`, alongside the `image` File field. A
malformed `data` field is re-raised as `RequestValidationError` rather than left as an uncaught
`pydantic.ValidationError`, so it still renders through the same canonical `validation-failed`
`422` envelope as any other invalid request body.

### `photo_key` is never client input

`FoodIntakeRequest` — the JSON body both endpoints ultimately register through — carries no
`photo_key` field. `FoodIntakeService.register` takes `photo_key` as an explicit parameter,
settable only by `ReceiptIntakeService.confirm_from_photo`, after it has uploaded the image itself
and computed the key server-side from `data.establishment_id` and a fresh UUID. A plain manual
`POST /food-intakes` therefore cannot claim a photo it never uploaded, and an attached photo's key
can never point at a different establishment than the intake it ends up on — both guaranteed by
construction, not by a validation rule that could be forgotten or bypassed.

`source` and `photo_key` remain independent columns, matching ADR-0013's own reasoning for
`source` (*"a photo-loaded intake is still a photo-loaded intake once its image is discarded"*):
CA 3's manual fallback produces `source = manual` with `photo_key` set, and that has to remain
legal. The reverse is not currently enforced — nothing rejects a plain JSON
`POST /food-intakes` request that sets `source = photo` without ever having gone through the photo
flow. Left unenforced for now: the two-endpoint split already makes this correct in ordinary use
(a photo can only ever be attached via `/confirm`, which always sets `photo_key` when it creates a
row), and no acceptance criterion currently depends on rejecting that specific mislabeling.

## Consequences

**Positives**

- No `food_intakes` row can end up referencing a photo that was never actually stored, and (bar
  the unknown-`food_id` case above) no stored photo can end up with nothing referencing it: the
  upload happens immediately before the row is written, in the same request.
- Abandoning the flow at any point before confirming leaves nothing behind in R2.
- A retried or duplicated confirmation (same client id, per ADR-0004) never uploads a second copy
  of the photo.
- `IObjectStorage`'s genericity means `valores_de_hierro`'s consent PDFs can reuse the same port
  and bucket later with no new infrastructure.
- The whole path — upload, idempotent replay, establishment/access checks, and the no-reupload
  guarantee — is verified against a real R2 bucket and a real Postgres instance, not only mocks.

**Negatives**

- The image travels over the network twice per confirmed intake (extraction, then confirmation) —
  an accepted bandwidth cost.
- An unknown `food_id` is still discovered only after the photo has already been uploaded,
  leaving a narrow, accepted orphan case with no cleanup mechanism.
- The integration tests that exercise this flow hit the real R2 bucket configured in `.env` and
  currently leave the objects they create behind, with no automated cleanup. Acceptable only if
  that bucket is a dedicated dev/test bucket, not one shared with real data.

**Neutral**

- `POST /food-intakes` does not reject a client-sent `source = photo` with no photo ever attached
  — a labelling oddity given the endpoint split above, not a data-integrity risk, and not
  currently worth a dedicated validation.
- No endpoint exists yet to read a stored receipt photo back (e.g. `GET .../photo`). Deferred:
  no current acceptance criterion requires viewing the photo again after upload.

## Alternatives considered

**Eager upload, at `/from-photo` time (the feature's first implementation)** — superseded; see
"Upload timing" above.

**A server-side temporary cache of the image bytes between propose and confirm**, to avoid the
double upload — rejected. It trades one cleanup problem (orphaned R2 objects) for a structurally
identical one (orphaned cache entries), while adding a dependency — a cache with an expiry policy
— this project does not otherwise need.

**A single endpoint for propose and confirm, distinguished by whether `items` is present in the
payload** — rejected. It makes whether a request can mutate the database and stock a runtime
condition rather than a fact visible in the route list.

**Extending `POST /food-intakes` itself to (conditionally) accept a photo**, instead of adding a
new endpoint — rejected. It is the pre-existing, already-tested US-3 manual entry point; changing
its request contract for a feature most of its callers will never use was judged worse than one
clearly-named additional endpoint.
