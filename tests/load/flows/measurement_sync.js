// Field workers syncing the height and weight they took offline: POST /measurements for
// seeded subjects of their establishment, some of them resent.
import { FIELD_WORKER_EMAILS, MARKER } from "../lib/config.js";
import { establishmentOf, loginAll, subjectsOf } from "../lib/api.js";
import { flowOptions } from "../lib/profile.js";
import { replayReturned200, syncOnce, workerFor } from "../lib/sync.js";
import { writeSummary } from "../lib/summary.js";

export const options = flowOptions([replayReturned200.name]);

export function setup() {
  return {
    workers: loginAll(FIELD_WORKER_EMAILS).map((token) => {
      const establishmentId = establishmentOf(token);
      return { token, establishmentId, subjectIds: subjectsOf(token, establishmentId) };
    }),
  };
}

function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

export default function ({ workers }) {
  const worker = workerFor(workers);
  syncOnce("/api/v1/measurements", worker.token, () => ({
    id: crypto.randomUUID(),
    subject_id: pick(worker.subjectIds),
    establishment_id: worker.establishmentId,
    weight_kg: 15 + Math.round(Math.random() * 300) / 10,
    height_cm: 95 + Math.round(Math.random() * 400) / 10,
    measured_at: new Date(Date.now() - 60_000).toISOString(),
    observation: MARKER,
  }));
}

export function handleSummary(data) {
  return writeSummary("measurement_sync", data, true);
}
