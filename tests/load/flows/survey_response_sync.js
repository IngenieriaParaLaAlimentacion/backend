// Field workers syncing the FIES surveys they took offline: POST to the load-test survey's
// responses, some of them resent.
import { FIELD_WORKER_EMAILS } from "../lib/config.js";
import { loadTestSurvey, loginAll } from "../lib/api.js";
import { flowOptions } from "../lib/profile.js";
import { replayReturned200, syncOnce, workerFor } from "../lib/sync.js";
import { writeSummary } from "../lib/summary.js";

const MAX_RESPONSE_NUMBER = 999_999;

export const options = flowOptions([replayReturned200.name]);

export function setup() {
  const tokens = loginAll(FIELD_WORKER_EMAILS);
  const survey = loadTestSurvey(tokens[0]);
  return {
    tokens,
    surveyId: survey.id,
    questions: survey.questions.map((question) => ({
      id: question.id,
      optionIds: question.options.map((option) => option.id),
    })),
  };
}

export default function ({ tokens, surveyId, questions }) {
  syncOnce(`/api/v1/surveys/${surveyId}/responses`, workerFor(tokens), () => ({
    id: crypto.randomUUID(),
    answers: Object.fromEntries(
      questions.map((question) => [
        question.id,
        question.optionIds[Math.floor(Math.random() * question.optionIds.length)],
      ]),
    ),
    response_number: 1 + Math.floor(Math.random() * MAX_RESPONSE_NUMBER),
    event_at: new Date(Date.now() - 60_000).toISOString(),
  }));
}

export function handleSummary(data) {
  return writeSummary("survey_response_sync", data, true);
}
