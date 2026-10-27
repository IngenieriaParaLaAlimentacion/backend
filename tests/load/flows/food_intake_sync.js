// Field workers syncing the food deliveries they logged offline: POST /food-intakes for
// their establishment, some of them resent.
import { FIELD_WORKER_EMAILS, MARKER } from "../lib/config.js";
import { establishmentOf, foodIds, loginAll } from "../lib/api.js";
import { flowOptions } from "../lib/profile.js";
import { replayReturned200, syncOnce, workerFor } from "../lib/sync.js";
import { writeSummary } from "../lib/summary.js";

const ITEMS_PER_INTAKE = 3;

export const options = flowOptions([replayReturned200.name]);

export function setup() {
  const tokens = loginAll(FIELD_WORKER_EMAILS);
  return {
    foods: foodIds(tokens[0]),
    workers: tokens.map((token) => ({ token, establishmentId: establishmentOf(token) })),
  };
}

export default function ({ foods, workers }) {
  const worker = workerFor(workers);
  syncOnce("/api/v1/food-intakes", worker.token, () => ({
    id: crypto.randomUUID(),
    establishment_id: worker.establishmentId,
    occurred_at: new Date(Date.now() - 60_000).toISOString(),
    comments: MARKER,
    origin_type: "national_government",
    is_recurring: false,
    items: Array.from({ length: ITEMS_PER_INTAKE }, (_, index) => ({
      food_id: foods[(__ITER + index) % foods.length],
      quantity: String(1 + Math.floor(Math.random() * 20)),
    })),
  }));
}

export function handleSummary(data) {
  return writeSummary("food_intake_sync", data, true);
}
