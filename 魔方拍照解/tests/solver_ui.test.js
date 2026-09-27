const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const vm = require("node:vm");
const { pathToFileURL } = require("node:url");

async function main() {
  const client = await import(
    pathToFileURL(path.join(__dirname, "..", "web", "solver-client.js")).href
  );
  const { describeSearchProgress, createSolveSnapshot, solveKey, metricExplanation } = client;
  const defaultRequest = createSolveSnapshot({ facelets: "state" });
  assert.equal(defaultRequest.metric, "HTM");
  assert.equal(defaultRequest.max_depth, 20);
  assert.ok(Object.isFrozen(defaultRequest));
  for (const [size, metric, budget] of [[2, "HTM", 11], [2, "QTM", 14], [3, "QTM", 26]]) {
    assert.equal(createSolveSnapshot({ cube_size: size, facelets: "state", metric }).max_depth, budget);
  }
  const qtmRequest = createSolveSnapshot({ facelets: "state", metric: "QTM" });
  assert.notEqual(solveKey(defaultRequest), solveKey(qtmRequest));
  assert.notEqual(solveKey(defaultRequest), solveKey({ ...defaultRequest, max_depth: 19 }));
  assert.match(metricExplanation("QTM"), /R2.*计 2 步/);
  assert.match(
    describeSearchProgress({ status: "queued", queue_position: 2, incumbent_depth: 20 }).status,
    /第 2 位/,
  );
  const running = describeSearchProgress({
    status: "running",
    metric: "QTM",
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
  assert.match(running.detail, /^QTM：/);

  await exerciseAppLifecycle(client);
  console.log("solver UI tests passed");
}

async function exerciseAppLifecycle(client) {
  const elements = new Map();
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      value: selector === "#metricSelect" ? "HTM" : selector === "#timeoutInput" ? "180" : "",
      textContent: "", innerHTML: "", disabled: false, handlers: {},
      addEventListener(name, callback) { this.handlers[name] = callback; },
      getContext() { return {}; },
      replaceChildren(child) { this.textContent = child.textContent; },
    });
    return elements.get(selector);
  }
  const requests = [], cancellations = [], cleared = [], polls = [];
  const timers = new Map();
  let pollResponse = null;
  let deferPoll = false;
  const context = vm.createContext({
    ...client, console,
    document: { querySelector: element, createElement: () => ({ textContent: "" }) },
    setTimeout(callback) { const id = timers.size + 1; timers.set(id, callback); return id; },
    clearTimeout(id) { cleared.push(id); timers.delete(id); },
    fetch(url, options) {
      if (url.endsWith("/cancel")) { cancellations.push(url); return Promise.resolve({}); }
      if (url === "/api/solve") return new Promise((resolve) => requests.push({
        body: JSON.parse(options.body),
        respond(data, ok = true) { resolve({ ok, json: async () => data }); },
      }));
      if (deferPoll) return new Promise((resolve) => polls.push({
        respond(data) { resolve({ ok: true, json: async () => data }); },
      }));
      return Promise.resolve({ ok: true, json: async () => pollResponse });
    },
  });
  // Skip photograph rendering only; exercise the real event listener, request,
  // response and polling code with controlled HTTP completion ordering.
  const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8")
    .replace(/^import[\s\S]*?from "[^"\n]+";\r?\n/gm, "")
    .replace(/initFaces\(\);\r?\nrenderAll\(\);/, "");
  vm.runInContext(source, context);
  vm.runInContext('colorAssessment = { valid: true, reasons: [], source: "manual" }; state.U.imageLoaded = true; state.U.stickers[0] = "R";', context);
  element("#faceletsText").value = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB";

  const oldPromise = vm.runInContext("solveCube()", context);
  assert.equal(requests[0].body.metric, "HTM");
  element("#metricSelect").value = "QTM";
  element("#metricSelect").handlers.change();
  assert.equal(requests.length, 1, "switching must not start a solve");
  assert.equal(vm.runInContext("state.U.stickers[0]", context), "R");
  assert.equal(vm.runInContext("state.U.imageLoaded", context), true);
  assert.match(element("#metricHint").textContent, /计 2 步/);
  const newPromise = vm.runInContext("solveCube()", context);
  assert.equal(requests[1].body.max_depth, 26);
  requests[0].respond({ ok: true, metric: "HTM", job_id: "old", depth: 1, solution: "R2", optimal: true });
  await oldPromise;
  assert.ok(cancellations.some((url) => url.includes("/old/cancel")));
  assert.equal(element("#solveBtn").disabled, true, "late response must not enable a new request's button");
  requests[1].respond({ ok: true, metric: "QTM", depth: 2, solution: "R2", optimal: true, elapsed_seconds: 0 });
  await newPromise;
  assert.match(element("#depthText").textContent, /2 步，QTM/);

  for (const status of ["queued", "running", "complete", "timeout", "budget_exhausted"]) {
    const result = { metric: "QTM", solution: "R2", depth: 2, optimal: status === "complete", elapsed_seconds: 0 };
    pollResponse = { ok: true, metric: "QTM", status, incumbent_depth: 2, result,
      progress: { metric: "QTM", lower_bound: 1, current_depth: 2, completed_depth: 1, nodes: 12, elapsed_seconds: 0 } };
    const pending = vm.runInContext("solveCube()", context);
    const jobId = `job-${status}`;
    requests.at(-1).respond({ ok: true, metric: "QTM", job_id: jobId, depth: 2, solution: "R2", optimal: false });
    await pending;
    await new Promise((resolve) => setImmediate(resolve));
    if (status === "budget_exhausted") assert.match(element("#depthText").textContent, /预算不足，尚未证明最短/);
    element("#metricSelect").value = "HTM";
    element("#metricSelect").handlers.change();
    assert.equal(element("#depthText").textContent, "");
    assert.match(element("#solutionText").textContent, /点击/);
    if (["queued", "running"].includes(status)) assert.ok(cancellations.some((url) => url.includes(`/${jobId}/cancel`)));
    assert.equal(vm.runInContext("state.U.stickers[0]", context), "R");
    assert.equal(vm.runInContext("state.U.imageLoaded", context), true);
    element("#metricSelect").value = "QTM";
    element("#metricSelect").handlers.change();
  }
  assert.ok(cleared.length >= 2, "switching clears queued/running poll timers");
  for (const status of ["timeout", "error"]) {
    pollResponse = { ok: true, metric: "QTM", status, message: "测试终态", incumbent_depth: null };
    const pending = vm.runInContext("solveCube()", context);
    requests.at(-1).respond({ ok: true, metric: "QTM", job_id: `empty-${status}`, depth: null, solution: "", optimal: false });
    await pending;
    await new Promise((resolve) => setImmediate(resolve));
    assert.match(element("#statusText").textContent, /尚未找到可执行解/);
    assert.equal(element("#solutionText").textContent, "尚未找到可执行解");
    assert.doesNotMatch(element("#statusText").textContent, /解可用|候选可用/);
  }
  deferPoll = true;
  const delayedPoll = vm.runInContext("solveCube()", context);
  requests.at(-1).respond({ ok: true, metric: "QTM", job_id: "late-get", depth: null, solution: "", optimal: false });
  await delayedPoll;
  assert.equal(polls.length, 1);
  element("#metricSelect").value = "HTM";
  element("#metricSelect").handlers.change();
  polls[0].respond({ ok: true, metric: "QTM", status: "complete", result: { metric: "QTM", solution: "R2", depth: 2, optimal: true } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(element("#depthText").textContent, "");
  assert.match(element("#solutionText").textContent, /点击/);
  assert.ok(cancellations.some((url) => url.includes("/late-get/cancel")));
  deferPoll = false;
  element("#metricSelect").value = "QTM";
  element("#metricSelect").handlers.change();
  for (const job_id of [undefined, "finished-budget-job"]) {
    const pending = vm.runInContext("solveCube()", context);
    requests.at(-1).respond({ ok: true, metric: "QTM", job_id, proof_status: "budget_exhausted",
      depth: null, solution: "", optimal: false, message: "预算不足" });
    await pending;
    assert.match(element("#statusText").textContent, /预算不足，尚未证明最短/);
    assert.doesNotMatch(element("#depthText").textContent, /后台.*搜索/);
    assert.equal(vm.runInContext("solveSession.jobId", context), null);
    assert.equal(vm.runInContext("solveSession.pollTimer", context), null);
  }
  // A late failed request cannot replace the new mode's status either.
  const failed = vm.runInContext("solveCube()", context);
  element("#metricSelect").value = "HTM";
  element("#metricSelect").handlers.change();
  requests.at(-1).respond({ ok: false, error: "old failure" }, false);
  await failed;
  assert.match(element("#statusText").textContent, /^HTM/);
  assert.equal(vm.runInContext("solveSession.pollTimer", context), null);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
