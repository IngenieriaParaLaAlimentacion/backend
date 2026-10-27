// Calls to the API that the flows share: login, and reading the fixtures each user works on.
import http from "k6/http";
import { sleep } from "k6";
import { BASE_URL, FIES_SURVEY_NAME, PASSWORD } from "./config.js";

const JSON_HEADERS = { "Content-Type": "application/json" };

// Login allows 20 per minute per IP, and every request from a runner shares one IP.
const LOGIN_INTERVAL_SECONDS = 3.1;

export function authHeaders(token) {
  return { ...JSON_HEADERS, Authorization: `Bearer ${token}` };
}

function getJson(path, token) {
  const response = http.get(`${BASE_URL}${path}`, {
    headers: authHeaders(token),
    tags: { name: "setup" },
  });
  if (response.status !== 200) {
    throw new Error(`GET ${path} answered ${response.status}: ${response.body}`);
  }
  return response.json();
}

function login(email, index) {
  if (index > 0) {
    sleep(LOGIN_INTERVAL_SECONDS);
  }
  const response = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({
      email,
      password: PASSWORD,
      device_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    }),
    { headers: JSON_HEADERS, tags: { name: "setup" } },
  );
  if (response.status !== 200) {
    throw new Error(`login of ${email} answered ${response.status}: ${response.body}`);
  }
  return response.json("access_token");
}

// Logs each user in once, so the VUs share the tokens instead of logging in themselves.
export function loginAll(emails) {
  return emails.map((email, index) => login(email, index));
}

export function establishmentOf(token) {
  const establishments = getJson("/api/v1/users/me/establishments", token);
  const approved = establishments.find((item) => item.status === "approved");
  if (!approved) {
    throw new Error("the load-test field worker has no approved establishment");
  }
  return approved.id;
}

export function subjectsOf(token, establishmentId) {
  const page = getJson(
    `/api/v1/subjects?establishment_id=${establishmentId}&page_size=100`,
    token,
  );
  return page.items.map((item) => item.id);
}

export function foodIds(token) {
  return getJson("/api/v1/food-catalog/foods?page_size=20", token).items.map(
    (item) => item.id,
  );
}

export function loadTestSurvey(token) {
  const available = getJson("/api/v1/surveys/available?page_size=100", token);
  const survey = available.items.find((item) => item.name === FIES_SURVEY_NAME);
  if (!survey) {
    throw new Error(`the survey "${FIES_SURVEY_NAME}" is not available`);
  }
  return getJson(`/api/v1/surveys/${survey.id}`, token);
}
