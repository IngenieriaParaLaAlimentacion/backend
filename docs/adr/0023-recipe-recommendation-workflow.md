# ADR-0023: Recipe recommendations with Gemini and the nutrition LP

- **Status**: Accepted
- **Date**: 2026-10-17
- **Related**: #170, #169, ADR-0022, ADR-0021, ADR-0014, ADR-0004

## Decision

The backend runs a fixed workflow: Gemini selects culinary ingredient
sets, `NutritionService.maximize_recipe` solves each set, and Gemini
writes names and preparation using the actual nonzero calculated ingredients.
The optimizer is unchanged. Calling it with all stock would produce one
nutrition optimum without culinary or cultural requirements; different culinary
candidates let the existing LP support two or three distinct meals. Distinct
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

`recipe_requests` stores input, actor, prompt version and time. Its immutable
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
last ten chosen recipes. The selection model reports whether a cultural dish is
viable; if so, at least one tagged candidate is required, with a bounded repair.
Ordinary dishes remain valid when stock cannot support cultural inspiration.
Culinary/cultural judgments remain model judgments rather than mathematical
properties guaranteed by the LP.

The LP's converter was an interface for #155. A catalog converter uses 1000 grams
per kilogram and optional reviewed `foods.grams_per_base_unit` for litres/units.
An admin endpoint configures the latter; missing factors are excluded with a
warning, never estimated from a food name. This small adapter can be replaced by
#155's implementation while retaining the same `GramsConverter` protocol.

## Consequences

This adds no workflow framework or separate service. Nutritional correctness is
owned by deterministic code; prompts handle preparation and cultural suitability.
There is no claim that the current LP imposes culinary portion caps or upper
bounds for sodium, saturated fat or sugar: ADR-0021 still governs its model.
Real-world culinary quality requires evaluation with reviewed examples; tests
use a scripted `ILlmClient`, never live model calls.
