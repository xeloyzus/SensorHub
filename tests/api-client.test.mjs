import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

function loadApiClient() {
  const context = {};
  runInNewContext(readFileSync(new URL("../app/static/js/api-client.js", import.meta.url), "utf8"), context);
  return context;
}

test("aggregateMetricHistory buckets near-identical sensor timestamps", () => {
  const api = loadApiClient();
  const history = {
    series: [
      {
        metric: "co2",
        points: [
          { time: "2026-01-01T00:00:00.101Z", value: 600 },
          { time: "2026-01-01T00:15:00.101Z", value: 800 },
        ],
      },
      {
        metric: "co2",
        points: [
          { time: "2026-01-01T00:00:00.902Z", value: 700 },
          { time: "2026-01-01T00:15:00.902Z", value: 900 },
        ],
      },
    ],
  };

  const result = JSON.parse(JSON.stringify(api.aggregateMetricHistory(history, "co2")));
  assert.deepEqual(result, [
    { time: "2026-01-01T00:00:00.000Z", value: 650 },
    { time: "2026-01-01T00:15:00.000Z", value: 850 },
  ]);
});

