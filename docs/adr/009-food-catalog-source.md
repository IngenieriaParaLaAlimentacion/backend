# ADR-0009: Use of SARA 2 as the official source for the food catalog (Nutrir)

- **Status**: Accepted
- **Date**: 2026-08-28
- **Deciders**: Backend team
- **Related**: --

## Context

The Nutrir module needs to record the food supplies that community kitchens receive, in a way that is consistent across 
establishments and usable for later analysis (nutritional deficit reports, ingredient-based meal planning, dashboards). 
For that to work, "carrots", "chicken breast", or "rice" must mean the same thing every time they are logged, regardless
of who enters the data or in which kitchen.

This requires a **standardized catalog of food types** that establishments select from when logging an intake, instead 
of free-text entry. Two properties are essential for this catalog to serve its purpose:

1. **Consistency**: the same food must always be represented by the same catalog entry, with a defined base unit of 
    measurement, so quantities can be aggregated, compared across kitchens, and later related to nutritional composition.
2. **Legitimacy and domain fit of the reference data**: since this catalog will underpin nutritional reasoning (deficits, 
    recommendations) further down in the Nutrir module, the names, categories, and nutritional composition values cannot
    be defined arbitrarily by the development team — they must come from a source that is both officially auditable and 
    representative of the actual foods, varieties, and nutrient composition found in Argentina, given that the platform's 
    entire purpose is addressing child food insecurity in Argentine communities.

Four candidate sources were evaluated against this need:

1. **SARA 2** — Table of chemical composition of foods for Argentina, compiled for ENNyS 2 (Ministerio de Salud de la 
    Nación, 2022).
2. **Argenfoods** — Food Composition Database (Universidad Nacional de Luján / ARGENFOODS Association, national 
    chapter of LATINFOODS-INFOODS/FAO).
3. **USDA FoodData Central** — the United States' national food composition database and REST API.
4. **Open Food Facts** — global collaborative database of packaged/branded products identified by barcode.

Each was assessed on: how current the content is, the usage license, technical accessibility of the data, and 
— critically — how well the food names, varieties, and nutrient composition values match what is actually consumed 
and received by Argentine community kitchens.

## Decision

We adopt **SARA 2** as the primary, official source to seed the food type catalog: food names, category grouping, 
and nutrient composition values.

Scope of this decision:
- The ~26 food groups from SARA 2 (organized following the logic of the Guías Alimentarias para la Población Argentina 
— GAPA) are taken as the reference categorization.
- From the food listing of each group, **every preparation state SARA 2 lists for a food is included** — raw/as-purchased
as well as cooking-state variants (boiled, sautéed, fried, etc.) — so the catalog can represent a supply a community
kitchen receives in any of these states, not only as-purchased.

This decision prioritizes domain fit over ease of ingestion: a technically superior but geographically foreign source
would shift the population effort from "extracting structured data from a PDF" to "translating and validating, food by 
food, whether an equivalent Argentine variety exists and whether its nutrient composition holds locally" — a cost that 
is harder to catch when it goes wrong, since it can silently produce inaccurate nutrient values rather than an obvious 
data-entry gap.

## Consequences

*Positives*
- Official, current (2022), and auditable source, satisfying the need for reference data that is not invented by intuition.
- Clear and favorable license: the Ministerio de Salud states its commitment to freely and openly distribute these 
tools for the scientific and academic community, with no restrictive clause on incorporation into information systems.
- Broad coverage (39 nutritional components, hundreds of foods grouped into 26 categories), sufficient to name and 
categorize the universe of supplies a community kitchen receives, including both fresh and industrialized foods, 
with composition values reflecting the actual Argentine food supply (local fortification standards, cattle breeds, 
regional varieties).
- Being the same source used by the Ministerio de Salud for ENNyS 2 gives methodological consistency with the other
official Argentine sources already anchoring this project (GAPA, UNICEF Argentina, FAO's FIES instrument).

*Negatives*
- SARA 2 is distributed as a PDF (unstructured text), not as a downloadable database in a structured format 
(CSV/JSON/API) — requires manual extraction and curation work to populate the seed. This is a meaningfully higher 
upfront ingestion cost than an API-based alternative like USDA FoodData Central.
- No continuous update cycle is evident beyond the single 2022 publication, unlike actively maintained alternatives.

*Neutral*
- Every preparation state SARA 2 lists for a food (raw, boiled, fried, baked, etc.) is kept as its own catalog entry
rather than collapsing to a single state per food — a scope decision specific to our domain, not a limitation of the
source itself.

## Alternatives considered

**USDA FoodData Central** — rejected despite being technically superior in several respects: it offers a real REST API, 
a public-domain (CC0) license with no restrictions, and covers over 600,000 foods with active maintenance (biannual 
updates for Foundation Foods, monthly for Branded Foods). It was rejected because it is built for the United States' 
food supply: food names, varieties, and branded products are American, and — more importantly — nutrient composition 
values reflect US-specific factors (fortification regulations, cattle breeds, soil/growing conditions) that can differ 
meaningfully from their Argentine equivalents. Populating the catalog from USDA would not eliminate manual work, it would 
relocate it: instead of extracting text from a PDF, the team would need to review each food individually to translate it, 
judge whether a real Argentine equivalent exists, and validate whether the imported composition values are still accurate 
locally — a slower and riskier process, since a wrong nutrient value is a silent error rather than an obvious gap. Given 
that the platform's stated purpose is addressing child food insecurity specifically in Argentina, and that it already 
anchors on Argentine and Argentina-adapted standards (GAPA, ENNyS, UNICEF Argentina, FAO's FIES instrument), domain fit 
was weighted above ingestion convenience.

**Argenfoods** — rejected as primary source. While its database website shows a page update date of 2024, the actual 
composition table index (the data that matters) is dated 10/01/2011, with a 1st edition copyright of 2010 — over a 
decade older than SARA 2, which already incorporated and expanded Argenfoods' data as one of its own inputs. 
Additionally, its usage license explicitly prohibits "incorporation into an information system... for commercial 
purposes" without the rights holder's written permission, a restriction SARA 2 does not have.

**Open Food Facts** — rejected as the primary source for the generic catalog, but not rejected from the project. 
Its nature is different: it is a database of packaged products identified by a specific barcode/brand, not of generic 
unbranded foods (a chard leaf, a cut of meat), which is what our catalog needs. It does, however, have clear advantages 
(open ODbL license allowing commercial use, real REST API, SDKs in multiple languages, daily updates) that make it a 
candidate for a future complementary feature: identifying specific packaged products via barcode scanning when logging 
a food intake.