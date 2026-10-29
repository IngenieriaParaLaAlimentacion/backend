// Settings shared by every flow: the target, the load-test users and the load profile.

export const BASE_URL = __ENV.BASE_URL;
export const PASSWORD = __ENV.LOAD_TEST_PASSWORD;

// Every record a flow creates carries it, as the seeded data does (tests/load/data/dataset.py).
export const MARKER = "LOADTEST";
export const FIES_SURVEY_NAME = `${MARKER} Encuesta FIES`;

export const ANALYST_EMAIL = "loadtest.analista@tpp.com";
export const FIELD_WORKER_EMAILS = Array.from(
  { length: 10 },
  (_, index) => `loadtest.relevador${String(index + 1).padStart(2, "0")}@tpp.com`,
);

// Concurrent users at each step. Every flow runs the same steps, one after the other.
export const STEPS = (__ENV.STEPS || "5,10,25,50").split(",").map(Number);
export const STEP_DURATION = __ENV.STEP_DURATION || "2m";

// Share of writes that resend a record already sent, as a worker retrying a sync does.
export const REPLAY_RATE = 0.2;
