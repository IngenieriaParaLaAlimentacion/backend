// Writes a flow's results: a markdown table with one row per step, and k6's full data.
import { STEPS } from "./config.js";
import { STEP_SECONDS, stepTag } from "./profile.js";

function metric(data, name, step) {
  const found = data.metrics[`${name}{step:${step}}`];
  return found ? found.values : {};
}

function ms(value) {
  if (value === undefined) {
    return "–";
  }
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
}

function percent(value) {
  return value === undefined ? "–" : `${(value * 100).toFixed(1)}%`;
}

function row(data, vus, withReplays) {
  const step = stepTag(vus);
  const duration = metric(data, "http_req_duration", step);
  const requests = metric(data, "http_reqs", step).count;
  const cells = [
    vus,
    requests === undefined ? "–" : (requests / STEP_SECONDS).toFixed(1),
    ms(duration["p(50)"]),
    ms(duration["p(95)"]),
    ms(duration["p(99)"]),
    percent(metric(data, "http_req_failed", step).rate),
  ];
  if (withReplays) {
    cells.push(percent(metric(data, "replay_returned_200", step).rate));
  }
  return `| ${cells.join(" | ")} |`;
}

// `withReplays` adds the share of resent records that came back as 200.
export function writeSummary(flow, data, withReplays = false) {
  const header = ["VUs", "req/s", "p50", "p95", "p99", "errors"];
  if (withReplays) {
    header.push("replays → 200");
  }
  const table = [
    `### ${flow}`,
    "",
    `| ${header.join(" | ")} |`,
    `|${header.map(() => "---").join("|")}|`,
    ...STEPS.map((vus) => row(data, vus, withReplays)),
    "",
  ].join("\n");

  return {
    stdout: `${table}\n`,
    [`tests/load/results/${flow}.md`]: table,
    [`tests/load/results/${flow}.json`]: JSON.stringify(data, null, 2),
  };
}
