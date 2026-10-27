// The stepped load profile: one constant-VUs scenario per step, run back to back, each
// tagged with its step so every metric can be read per step.
import { STEPS, STEP_DURATION } from "./config.js";

export function stepTag(vus) {
  return String(vus).padStart(3, "0");
}

function seconds(duration) {
  const match = /^(\d+)(s|m)$/.exec(duration);
  if (!match) {
    throw new Error(`STEP_DURATION must look like 30s or 2m, not ${duration}`);
  }
  return Number(match[1]) * (match[2] === "m" ? 60 : 1);
}

export const STEP_SECONDS = seconds(STEP_DURATION);

function scenarios() {
  return Object.fromEntries(
    STEPS.map((vus, index) => [
      `step_${stepTag(vus)}`,
      {
        executor: "constant-vus",
        vus,
        duration: STEP_DURATION,
        startTime: `${index * STEP_SECONDS}s`,
        gracefulStop: "5s",
        tags: { step: stepTag(vus) },
      },
    ]),
  );
}

// k6 only reports a tagged submetric when a threshold names it. These conditions always
// hold: they exist for the per-step summary, not to pass or fail a run.
function reportingThresholds(extraMetrics) {
  // First writes and replays apart, to compare what each costs.
  const thresholds = {
    "http_req_duration{kind:write}": ["max>=0"],
    "http_req_duration{kind:replay}": ["max>=0"],
  };
  for (const vus of STEPS) {
    const step = `{step:${stepTag(vus)}}`;
    thresholds[`http_req_duration${step}`] = ["max>=0"];
    thresholds[`http_reqs${step}`] = ["count>=0"];
    thresholds[`http_req_failed${step}`] = ["rate>=0"];
    for (const metric of extraMetrics) {
      thresholds[`${metric}${step}`] = ["rate>=0"];
    }
  }
  return thresholds;
}

// The options every flow uses. `extraMetrics` are custom Rate metrics to report per step.
export function flowOptions(extraMetrics = []) {
  return {
    scenarios: scenarios(),
    thresholds: reportingThresholds(extraMetrics),
    summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max"],
    // setup() logs every user in at the pace the login rate limit allows.
    setupTimeout: "2m",
  };
}
