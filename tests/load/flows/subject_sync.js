// Field workers syncing the subjects they registered offline: POST /subjects with ids made
// on the device, some of them resent.
import { FIELD_WORKER_EMAILS, MARKER } from "../lib/config.js";
import { loginAll } from "../lib/api.js";
import { flowOptions } from "../lib/profile.js";
import { replayReturned200, syncOnce, workerFor } from "../lib/sync.js";
import { writeSummary } from "../lib/summary.js";

// Above the seeded DNIs (from 80,000,001) and below the E2E reference ones (from
// 90,000,001). Each VU gets its own block, so two subjects never share a DNI.
const FIRST_DNI = 81_000_000;
const DNIS_PER_VU = 50_000;

export const options = flowOptions([replayReturned200.name]);

let created = 0;

export function setup() {
  return { tokens: loginAll(FIELD_WORKER_EMAILS) };
}

export default function ({ tokens }) {
  syncOnce("/api/v1/subjects", workerFor(tokens), () => {
    created += 1;
    return {
      id: crypto.randomUUID(),
      dni: FIRST_DNI + __VU * DNIS_PER_VU + created,
      sex: Math.random() < 0.5 ? "female" : "male",
      name: "Sincronizado",
      last_name: `${MARKER} Carga`,
      birth_date: "2019-06-15",
      is_rural: false,
      is_indigenous: false,
    };
  });
}

export function handleSummary(data) {
  return writeSummary("subject_sync", data, true);
}
