// Paginated listings an analyst browses in the backoffice: establishments, subjects and
// measurements, on random pages so the database cannot serve the same page every time.
import http from "k6/http";
import { check } from "k6";
import { ANALYST_EMAIL, BASE_URL } from "../lib/config.js";
import { authHeaders, loginAll } from "../lib/api.js";
import { flowOptions } from "../lib/profile.js";
import { writeSummary } from "../lib/summary.js";

const PAGE_SIZE = 20;
// The seeded subjects fill 100 pages and their measurements 300 at this size.
const LISTINGS = [
  { name: "establishments", path: "/api/v1/establishments", pages: 1 },
  { name: "subjects", path: "/api/v1/subjects", pages: 100 },
  { name: "measurements", path: "/api/v1/measurements", pages: 300 },
];

export const options = flowOptions();

export function setup() {
  const [token] = loginAll([ANALYST_EMAIL]);
  return { token };
}

export default function ({ token }) {
  for (const listing of LISTINGS) {
    const page = 1 + Math.floor(Math.random() * listing.pages);
    const response = http.get(
      `${BASE_URL}${listing.path}?page=${page}&page_size=${PAGE_SIZE}`,
      { headers: authHeaders(token), tags: { name: listing.name } },
    );
    check(response, { [`${listing.name} returns 200`]: (r) => r.status === 200 });
  }
}

export function handleSummary(data) {
  return writeSummary("listings", data);
}
