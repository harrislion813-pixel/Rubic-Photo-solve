const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

async function main() {
  const { describeSearchProgress } = await import(
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
  console.log("solver UI tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
