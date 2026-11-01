// The offline-first sync pattern every write flow follows: most writes send a new record,
// and some resend one already sent, as a worker does when a sync is retried.
import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";
import { BASE_URL, REPLAY_RATE } from "./config.js";
import { authHeaders } from "./api.js";

// Share of resent records the API answered with 200, the idempotent replay.
export const replayReturned200 = new Rate("replay_returned_200");

// Records this VU already sent, kept to be resent.
const sent = [];

// Sends one record to `path`: a new one built by `build`, or one already sent.
export function syncOnce(path, token, build) {
  const replay = sent.length > 0 && Math.random() < REPLAY_RATE;
  const body = replay ? sent[Math.floor(Math.random() * sent.length)] : build();
  const response = http.post(`${BASE_URL}${path}`, JSON.stringify(body), {
    headers: authHeaders(token),
    tags: { kind: replay ? "replay" : "write" },
  });

  if (replay) {
    const ok = response.status === 200;
    replayReturned200.add(ok);
    check(response, { "replay returns 200": () => ok });
  } else {
    check(response, { "write returns 201": (r) => r.status === 201 });
    if (response.status === 201) {
      sent.push(body);
    }
  }
}

// Each VU acts as one of the field workers, spread evenly over them.
export function workerFor(workers) {
  return workers[(__VU - 1) % workers.length];
}
