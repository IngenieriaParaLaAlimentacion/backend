// Checks the target is up and the load-test data is usable: the backend is ready, a
// load-test user logs in, and an authenticated listing answers. Fails on any failed check.
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL;

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    checks: ["rate==1"],
  },
};

export default function () {
  const ready = http.get(`${BASE_URL}/ready`);
  check(ready, { "backend is ready": (r) => r.status === 200 });

  const login = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({
      email: "loadtest.relevador01@tpp.com",
      password: __ENV.LOAD_TEST_PASSWORD,
      device_id: "00000000-0000-4000-8000-000000000001",
    }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(login, { "load-test user logs in": (r) => r.status === 200 });
  if (login.status !== 200) {
    return;
  }

  const subjects = http.get(`${BASE_URL}/api/v1/subjects?page_size=20`, {
    headers: { Authorization: `Bearer ${login.json("access_token")}` },
  });
  check(subjects, {
    "subjects listing answers": (r) => r.status === 200,
    "subjects listing has the seeded data": (r) => r.json("total") > 0,
  });
}

export function handleSummary(data) {
  const checks = data.root_group.checks
    .map((c) => `| ${c.name} | ${c.passes} | ${c.fails} |`)
    .join("\n");
  return {
    stdout: `smoke: ${data.metrics.checks.values.passes} checks passed, ${data.metrics.checks.values.fails} failed\n`,
    "tests/load/results/smoke.md": `### smoke\n\n| Check | Passed | Failed |\n|---|---|---|\n${checks}\n`,
  };
}
