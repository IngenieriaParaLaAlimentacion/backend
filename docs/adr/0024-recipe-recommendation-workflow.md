# ADR-0024: Recipe recommendations with Gemini and the nutrition LP

> The direct Gemini transport choice is superseded by
> [ADR-0027](0027-openrouter-free-inference.md). The recipe workflow,
> deterministic nutrition optimizer and persistence rules still apply.

- **Status**: Accepted
- **Date**: 2026-10-17
- **Related**: #170, #169, ADR-0022, ADR-0021, ADR-0014, ADR-0004

## Decision

The backend runs a fixed workflow: Gemini selects culinary ingredient
sets, `NutritionService.maximize_recipe` solves each set, and Gemini
writes names and preparation using the actual nonzero calculated ingredients.
The optimizer is unchanged. Calling it with all stock would produce one
nutrition optimum without culinary or cultural requirements; different culinary
candidates let the existing LP support distinct meals. Generation aims for
two or three and can return one independently valid recipe. Distinct
preparations may share an ingredient set and the same optimized quantities.

Reuse the existing `GeminiLlmClient` behind `ILlmClient` and the shared
`get_llm_client` dependency for both receipt extraction and recipe generation.
Its `complete` method already accepts a JSON response schema and handles retries
and model fallback. LangChain adds no required capability to this fixed workflow;
we defer adopting it until a concrete integration need justifies the dependency.
Backend code controls calls and validation; there is no model-controlled tool
loop. One selection call, at most one repair, and one writing call bound logical
turns to three. Selection, history and reuse do not construct a model.

Nutritional shortfalls, including insufficient energy, are offered explicitly.
Only stock with no usable energy prevents generation. Ingredient count 5–8 is
guidance. Model quantities are ignored; the backend rounds down to stock's
0.001-unit precision and recalculates indicators and shortfalls. Fractions in
engine indicators are also exposed as explicit percentages for clients.

## Persistence and concurrency

`recipe_requests` stores the fixed input snapshot and time. Unused request-level
`user_id` and persisted `prompt_version` have been removed before deployment.
Selection `user_id` attributes the actual stock deduction. The prompt version
remains a code constant used in structured failure logs, not an unused history
field. Proposal `position` preserves its zero-based display order. Immutable
`recipe_proposals` store complete JSON snapshots including final quantities and
indicators. No request is persisted until both AI stages have validated.
`recipe_selections` has one row per request and a unique outflow id. Its composite
foreign key ensures that the selected proposal belongs to that request.

Choosing locks the request row, checks the existing selection, invokes the food
outflow service with `commit=False`, saves the choice, and commits once. Stock
updates retain their conditional guards. Any shortage rolls back both the
outflow and choice. Every replay checks current access before returning a result.

Reuse creates a new request under a client-generated id, scales recorded
stock-unit quantities, recalculates indicators, and chooses the copy without AI.
An advisory transaction lock serializes concurrent creation of the same id;
reusing an id with different source/count/establishment is a conflict.
Proposals do not expire; current stock is always checked at selection.

## Culture and mass conversion

The establishment ficha from #200 is the single source of cultural context:
`characterization.cultural_identities` and `cultural_identities_other`. Recipes
reuse its domain catalog, extended with `paraguayan` and `bolivian` without
reinterpreting existing identities. Editing uses the ficha endpoint and its
admin/superadmin and approved field-worker permissions. There is no separate
establishment culture column or recipe-specific culture editor. Both prompts
receive the codes and optional other description; selection also receives the
last ten chosen recipes. Cultural inspiration is a preference: the model's
self-reported viability does not trigger rejection or another call. If no final
recipe has a cultural tag, return the valid recipes with a cultural-unavailable
warning.
Ordinary dishes remain valid when stock cannot support cultural inspiration.
Culinary/cultural judgments remain model judgments rather than mathematical
properties guaranteed by the LP.

The LP converts stock to grams and its result back to stock units through
`GramsConverter`, which reads each food's density and unit weight from the
shared `food_equivalences` (ADR-0025). Kilograms need no factor; missing
factors are excluded with a warning, never estimated from a food name. Recipes
keep no conversion data of their own.

## Consequences

This adds no workflow framework or separate service. Nutritional correctness is
owned by deterministic code; prompts handle preparation and cultural suitability.
There is no claim that the current LP imposes culinary portion caps or upper
bounds for sodium, saturated fat or sugar: ADR-0021 still governs its model.
Real-world culinary quality requires evaluation with reviewed examples; tests
use a scripted `ILlmClient`, never live model calls.

## Review refinements

Generation loads authorization, stock, nutrient compositions and recent choices
once. It copies the data into plain snapshots, then rolls back the read-only
transaction before any model call. Rollback expires ORM state, so no ORM object
is passed to generation or the LP. `maximize_stocked_recipe` accepts the already
authorized snapshot and does no DB I/O; the existing public nutrition entry point
still performs its own authorization and reads. Candidate solves use the same
snapshot even if stock changes during model calls. Saving opens a short write
transaction; choosing always rechecks live stock atomically.

The workflow separates snapshot loading, bounded selection/repair, writing
validation and persistence. Structured warnings report stage, controlled failure
reason, prompt version and controlled rejection codes. Provider failures,
timeouts, schema errors, bad references, prose quantities and duplicates can be
distinguished without logging prompts, stock, model prose or provider messages.

Recipe listing offers both request history and individual proposal pagination,
plus read-only detail for chosen and unchosen proposals. All use the same access
policy: approved establishment relations for field workers and analysts;
admins/superadmins are unrestricted by establishment.

AI endpoints share the authenticated-user quota `RATE_LIMIT_AI_USER` (20/hour
by default) for recipe generation and receipt extraction. Exceeding it returns
429 with Retry-After before model work. Existing Redis outage fallback remains
per process; quotas are separate per replica while degraded. This bounds request
rate, not provider spend globally; provider retries and fallback still count as
one incoming request, and no global budget or retention policy is introduced.

Final-quantity shortfall evaluation and named tolerances live in
`nutrition.shortfalls`; recipes only consume them. The reference profile remains
the source of macro ranges and GAPA minima for both evaluation and the LP, whose
objective and constraints are unchanged. `NutritionService.target_energy_kcal`
is shared by optimization and reuse. Reuse distinguishes missing ingredients,
changed units and quantities below stock precision with explicit domain errors.

## Runtime resource and output bounds

The generation service runs under a configurable 90-second total deadline,
including read preparation, solver awaits, retry/backoff/fallback and persistence.
Deadline expiry cancels the active task, rolls back and returns the distinct
504 `recipes/generation-timeout` error. It does not extend a shorter deployment
proxy deadline or add idempotency; gateway/client timeouts must be aligned with
`RECIPE_GENERATION_TIMEOUT_SECONDS`. A solver thread already running at
cancellation can finish its existing bounded solve; it holds no DB connection.

A single lazy Gemini client is owned by each app's lifespan and explicitly closed
with its supplied HTTP client at shutdown. SDK-internal retries are disabled so
there is one retry owner (Tenacity), covered by the request deadline. The response
cap is 8192 tokens by default. Gemini 3 uses low thinking and the recommended
default temperature; temperature and seed can be explicitly configured, without
claiming deterministic reproduction. See Google's
[Gemini 3 temperature guidance](https://ai.google.dev/gemini-api/docs/gemini-3).

The shared client logs only response length, model/token metadata and safe error
class/status, never model prose or raw provider errors. Quantity detection now
covers common Argentine Spanish unit names and abbreviations, spelled-out
numbers and fractions; durations and temperatures remain allowed. Generation still has no idempotency key; see the partial-result decision below.

## Partial results and cultural preference

Preserve each independently valid recipe rather than rejecting its siblings.
The provider still receives the complete candidate/writing schemas, but runtime
parsing first validates only the outer list, then validates each item with its
full Pydantic schema and semantic checks. Thus one malformed entry cannot make
valid entries disappear. Writing must still reference exactly the calculated
ingredients, retain its culture and contain no ingredient amounts in prose.
Duplicate preparations and unknown output IDs are skipped. With duplicate
presentations for the same proposal, keep the first independently valid one;
never return that proposal twice. Return only validated snapshots, even if one
survives. Fail without persistence only when none survives, or when the provider
or the outer response cannot be used.

Selection may use its existing single repair only when no usable candidate was
found. There is no extra selection call to complete a count or obtain a cultural
recipe, and no writing repair. The ceiling remains three logical model calls
under the existing request deadline.

Missing cultural inspiration is reported using `recipes/cultural-unavailable`
regardless of the model's viability boolean. Reduced alternatives are reported
using `recipes/fewer-alternatives`. Both use the existing per-proposal warnings
list and persist into history/reuse; consumers must distinguish them from
nutritional metadata gaps. No stock is reserved or deducted during generation.
