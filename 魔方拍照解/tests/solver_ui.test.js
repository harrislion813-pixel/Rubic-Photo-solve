const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

async function main() {
  const { describeQtmTiming, describeSearchProgress } = await import(
    pathToFileURL(path.join(__dirname, "..", "web", "solver-client.js")).href
  );
  assert.match(
    describeSearchProgress({ status: "queued", queue_position: 2, incumbent_depth: 20 }).status,
    /第 2 位/,
  );
  const running = describeSearchProgress({
    status: "running",
    incumbent_depth: 20,
    progress: {
      lower_bound: 16,
      current_depth: 18,
      completed_depth: 17,
      nodes: 1234567,
      elapsed_seconds: 4.25,
    },
  });
  assert.match(running.status, /18 步/);
  assert.match(running.detail, /≤ 17 步/);
  assert.match(running.detail, /18–20 步/);
  const waiting = describeSearchProgress({
    metric: "QTM", status: "running", candidate_cost: 24, proven_lower_bound: 18, proof_gap: 6,
    progress: { phase: "waiting_strong", current_depth: 18, completed_depth: 17, elapsed_seconds: 2 },
  });
  assert.match(waiting.status, /校验强表/);
  assert.match(waiting.detail, /候选 24 步；已证下界 18 步；差值 6 步/);
  assert.equal(describeQtmTiming({ first_candidate_seconds: 0.83, request_elapsed_seconds: 8.92 },
    { elapsed_seconds: 7.1 }), "首候选 0.83s，原生搜索 7.10s，请求累计 8.92s");
  assert.equal(describeQtmTiming({ first_candidate_seconds: null, elapsed_seconds: undefined }), "");
  console.log("solver UI tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
