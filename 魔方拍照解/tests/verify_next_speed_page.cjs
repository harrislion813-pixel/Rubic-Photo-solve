// Browser acceptance uses the normal launcher and never overrides solver defaults.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { performance } = require("node:perf_hooks");
const crypto = require("node:crypto");
const { AtomicReportWriter } = require("./next_speed_atomic_report.cjs");

const [configPath, output, playwrightPath] = process.argv.slice(2);
const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
const { chromium } = require(playwrightPath || "playwright");
const root = path.resolve(__dirname, "..");
const cases = JSON.parse(fs.readFileSync(path.join(root, "tests/initial_solver_cases.json"), "utf8"));
const report = { entry: "启动魔方求解器.cmd", solverOverrides: {}, timeout: 30,
  formalMatrix: config.formalMatrix !== false, memoryIntervalSeconds: 0.5,
  memoryScope: "launcher_descendant_native_process_lifetime_peak",
  persistenceScope: "Full checkpoints only before each launcher, after owned process-tree cleanup, and at final exit; raw response events remain in memory during search",
  config, configSha256: require("node:crypto").createHash("sha256").update(fs.readFileSync(configPath)).digest("hex"),
  cases: [], failures: [], order: [["baseline", "current"], ["current", "baseline"], ["baseline", "current"]] };
const reportWriter = new AtomicReportWriter(output, () => ({ ...report, reportPersistence: reportWriter.diagnostics() }));
const save = () => reportWriter.requestSave();
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");

async function startMemoryObserver(rootPid, memoryPath) {
  const processHandle = spawn(config.memoryPython || path.join(root, ".venv/Scripts/python.exe"),
    ["-u", path.join(root, "tests/observe_next_speed_memory.py"), "--root-pid", String(rootPid), "--output", memoryPath],
    { windowsHide: true });
  const logs = [];
  processHandle.stderr.on("data", (data) => logs.push(data.toString("utf8")));
  try { await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("OS memory observer did not become ready")), 10000);
    processHandle.stdout.on("data", (data) => {
      if (data.toString("utf8").includes('"ready": true')) { clearTimeout(timer); resolve(); }
    });
    processHandle.once("error", (error) => { clearTimeout(timer); reject(error); });
    processHandle.once("exit", (code) => { clearTimeout(timer); reject(new Error(`memory observer exited ${code}: ${logs.join("")}`)); });
  }); } catch (error) { processHandle.kill(); throw error; }
  return { processHandle, memoryPath, logs };
}

async function stopMemoryObserver(observer) {
  if (observer.processHandle.exitCode === null) observer.processHandle.stdin.end("stop\n");
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      observer.processHandle.kill();
      reject(new Error("memory observer cleanup exceeded five seconds"));
    }, 5000);
    const finish = (code) => {
      clearTimeout(timer);
      code === 0 ? resolve() : reject(new Error(`memory observer exited ${code}: ${observer.logs.join("")}`));
    };
    if (observer.processHandle.exitCode !== null) finish(observer.processHandle.exitCode);
    else observer.processHandle.once("exit", finish);
  });
  return JSON.parse(fs.readFileSync(observer.memoryPath, "utf8"));
}

async function start(packageRoot, memoryPath) {
  const env = { ...process.env, CUBE_NO_BROWSER: "1", PYTHONUTF8: "1" };
  for (const key of Object.keys(env)) {
    if (/^CUBE_/.test(key) && key !== "CUBE_NO_BROWSER" || key === "PYTHONPATH") delete env[key];
  }
  const processHandle = spawn(env.ComSpec || "cmd.exe", ["/d", "/c", report.entry], {
    cwd: packageRoot, env, windowsHide: true,
  });
  const logs = [];
  let url;
  processHandle.stdout.on("data", (data) => {
    const text = data.toString("utf8");
    logs.push(text);
    url ||= text.match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0];
  });
  processHandle.stderr.on("data", (data) => logs.push(data.toString("utf8")));
  processHandle.on("error", (error) => logs.push(error.message));
  let observer;
  try { observer = await startMemoryObserver(processHandle.pid, memoryPath); }
  catch (error) {
    if (processHandle.pid) spawnSync("taskkill.exe", ["/PID", String(processHandle.pid), "/T", "/F"], { windowsHide: true });
    throw error;
  }
  const until = performance.now() + 30000;
  while (!url && processHandle.exitCode === null && performance.now() < until) await pause(50);
  if (!url) {
    try { await stopMemoryObserver(observer); }
    finally { spawnSync("taskkill.exe", ["/PID", String(processHandle.pid), "/T", "/F"], { windowsHide: true }); }
    throw new Error(`normal launcher failed: ${logs.join("")}`);
  }
  return { processHandle, url, logs, observer };
}

async function inspectLayout(page) {
  return page.evaluate(() => {
    const selectors = ["#statusText", "#solutionText", "#depthText", "#solveBtn"];
    const boxes = selectors.map((selector) => {
      const element = document.querySelector(selector);
      const rect = element.getBoundingClientRect();
      return { selector, x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        clipped: element.scrollWidth > element.clientWidth + 1 };
    });
    const overlaps = [];
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        if (Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 1 &&
            Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 1) {
          overlaps.push([a.selector, b.selector]);
        }
      }
    }
    const canvases = [...document.querySelectorAll("canvas.preview")].map((canvas) => {
      const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
      const colors = new Set();
      for (let i = 0; i < pixels.length; i += 256) colors.add([...pixels.slice(i, i + 3)].join(","));
      return { width: canvas.width, height: canvas.height, sampledColors: colors.size };
    });
    return { viewport: { width: innerWidth, height: innerHeight },
      documentWidth: document.documentElement.scrollWidth, boxes, overlaps, canvases };
  });
}

async function runCase(browser, frozen, metric, label, repeat) {
  const packageRoot = path.resolve(config.packages[label]);
  const result = { name: frozen.name, metric, label, repeat, packageRoot,
    facelets: frozen.facelets, faceletsSha256: frozen.facelets_sha256, images: frozen.images,
    newProcess: false, events: [], pageErrors: [], logs: [], normalPollRequests: [], solveRequests: 0 };
  report.cases.push(result);
  save();
  let launch, context, page;
  const pending = new Set();
  let started;
  try {
  // Serialize previous evidence before any native process is launched. During
  // active search only append raw events in memory; full-report writes would
  // grow across the matrix and distort response observation on later requests.
  await reportWriter.flush();
  console.log(JSON.stringify({ event: "case_start", name: frozen.name, metric, label, repeat }));
  launch = await start(packageRoot, path.join(path.dirname(output), `${label}-${metric}-${frozen.name}-${repeat}-memory.json`));
  Object.assign(result, { url: launch.url, launcherPid: launch.processHandle.pid, newProcess: true, logs: launch.logs });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  page = await context.newPage();
  page.on("pageerror", (error) => result.pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().endsWith("/api/solve") && request.method() === "POST") {
      result.solveRequests += 1;
      started ??= performance.now();
      result.request = request.postDataJSON();
    } else if (/\/api\/solve\/[^/]+$/.test(request.url()) && request.method() === "GET") {
      result.normalPollRequests.push({ seconds: (performance.now() - started) / 1000, url: request.url() });
    }
  });
  page.on("response", (response) => {
    if (!/\/api\/solve(?:\/[^/]+)?$/.test(response.url())) return;
    const task = (async () => {
      const data = await response.json();
      const seconds = (performance.now() - started) / 1000;
      result.events.push({ seconds, data, httpStatus: response.status() });
      if (data.job_id) result.jobId = data.job_id;
      if (["complete", "timeout", "cancelled", "error", "budget_exhausted"].includes(data.status) || data.proof_status === "complete") {
        result.final = data;
      }
    })().catch((error) => result.pageErrors.push(error.message));
    pending.add(task);
    task.finally(() => pending.delete(task));
  });
    await page.goto(launch.url, { waitUntil: "networkidle" });
    result.version = await (await context.request.get(`${launch.url}api/version`)).json();
    await page.waitForFunction((metric) => !document.querySelector(`#metricSelect option[value="${metric}"]`).disabled, metric);
    for (const [index, face] of [..."URFDLB"].entries()) {
      await page.locator(`[data-face="${face}"] .file-input`).setInputFiles(path.join(root, frozen.image_paths[index]));
      await page.waitForFunction((face) => !document.querySelector(`[data-face="${face}"] .adjust-region`).disabled, face);
    }
    result.automaticFacelets = await page.locator("#faceletsText").inputValue();
    result.automaticFaceletsSha256 = sha256(result.automaticFacelets);
    result.automaticColorGrid = await page.evaluate(() => Object.fromEntries([..."URFDLB"].map((face) => [face,
      [...document.querySelectorAll(`[data-face="${face}"] .sticker`)].map((sticker) => ({ color: sticker.dataset.color,
        lowConfidence: sticker.classList.contains("low-confidence"), title: sticker.title }))])));
    result.referenceDifferences = [...frozen.facelets].flatMap((reference, index) =>
      reference === result.automaticFacelets[index] ? [] : [{ face: "URFDLB"[Math.floor(index / 9)],
        stickerIndex: index % 9, automatic: result.automaticFacelets[index] ?? null, reference }]);
    result.inputCorrection = { method: "advanced Facelets field explicitly filled with frozen reference",
      changedStickers: result.referenceDifferences.length, manuallyClickedStickers: 0 };
    await page.locator(".advanced-panel > summary").click();
    await page.locator("#faceletsText").fill(frozen.facelets);
    await page.locator("#metricSelect").selectOption(metric);
    await page.locator("#timeoutInput").fill("30");
    await page.evaluate(() => {
      window.__proofUiEvents = [];
      const observe = () => window.__proofUiEvents.push({ seconds: performance.now() / 1000,
        status: document.querySelector("#statusText").textContent,
        solution: document.querySelector("#solutionText").textContent,
        detail: document.querySelector("#depthText").textContent });
      document.querySelector("#solveBtn").addEventListener("click", () => {
        window.__proofUiStarted = performance.now() / 1000;
      }, { once: true });
      new MutationObserver(observe).observe(document.querySelector(".result-panel"),
        { childList: true, subtree: true, characterData: true });
    });
    await page.locator("#solveBtn").click();
    await page.waitForFunction(() => /已确认|尚未证明|已取消|验证失败|求解失败/.test(
      document.querySelector("#statusText").textContent), null, { timeout: 36000 });
    result.pageWallSeconds = (performance.now() - started) / 1000;
    await Promise.all([...pending]);
    result.ui = await page.evaluate(() => ({
      status: document.querySelector("#statusText").textContent,
      solution: document.querySelector("#solutionText").textContent,
      detail: document.querySelector("#depthText").textContent,
      events: window.__proofUiEvents.map((event) => ({ ...event, seconds: event.seconds - window.__proofUiStarted })),
    }));
    // One final read captures resource cleanup after the normal one-second UI polling.
    if (result.jobId) {
      await pause(600);
      result.afterCleanup = await (await context.request.get(`${launch.url}api/solve/${result.jobId}`)).json();
    }
    result.desktop = await inspectLayout(page);
    if (repeat === 0) {
      result.desktopScreenshot = path.join(path.dirname(output), `${label}-${metric}-${frozen.name}-desktop.png`);
      await page.screenshot({ path: result.desktopScreenshot, fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    result.mobile = await inspectLayout(page);
    if (repeat === 0) {
      result.mobileScreenshot = path.join(path.dirname(output), `${label}-${metric}-${frozen.name}-mobile.png`);
      await page.screenshot({ path: result.mobileScreenshot, fullPage: true });
    }
    for (const layout of [result.desktop, result.mobile]) {
      assert.ok(layout.documentWidth <= layout.viewport.width + 1, "horizontal overflow");
      assert.deepEqual(layout.overlaps, [], "overlapping solver text");
      assert.ok(layout.boxes.every((box) => !box.clipped), "clipped solver text");
      assert.equal(layout.canvases.length, 6);
      assert.ok(layout.canvases.every((canvas) => canvas.sampledColors > 15), "blank photo preview");
    }
    assert.deepEqual(result.pageErrors, []);
    assert.ok(!/undefined|NaN/.test(result.ui.detail));
    assert.equal(result.request.timeout_seconds, 30);
    assert.equal(result.request.facelets, frozen.facelets);
    assert.equal(result.request.metric, metric);
    assert.equal(result.solveRequests, 1, "one fresh solve request per package launch required");
    assert.ok(result.final, "normal page polling did not observe a terminal response");
    assert.ok(["complete", "timeout", "budget_exhausted"].includes(result.final.status || result.final.proof_status),
      "cancelled/error requests fail the acceptance gate");
    console.log(JSON.stringify({ name: result.name, metric, label, repeat, status: result.final?.status,
      cost: result.final?.result?.depth, pageWallSeconds: result.pageWallSeconds,
      firstCandidate: result.afterCleanup?.first_candidate_seconds,
      strongReady: result.afterCleanup?.strong_ready_seconds,
      strongAdopted: result.afterCleanup?.strong_adopted_seconds }));
  } catch (error) {
    result.failure = error.stack;
    report.failures.push({ name: frozen.name, metric, label, repeat, failure: error.stack });
  } finally {
    if (context) {
      try { await context.close(); }
      catch (error) { report.failures.push({ name: frozen.name, metric, label, repeat, failure: error.stack }); }
    }
    if (launch) {
      try {
        result.memory = await stopMemoryObserver(launch.observer);
        assert.ok(result.memory.native_process_lifetime_peak_bytes > 0, "no native descendant OS lifetime-peak sample");
      } catch (error) {
        result.memoryFailure = error.stack;
        report.failures.push({ name: frozen.name, metric, label, repeat, failure: error.stack });
      } finally {
        // Kill only this launcher's process tree, including its paused resident.
        const stopped = spawnSync("taskkill.exe", ["/PID", String(launch.processHandle.pid), "/T", "/F"], { windowsHide: true });
        result.processTreeStopped = stopped.status === 0;
        if (!result.processTreeStopped) report.failures.push({ name: frozen.name, metric, label, repeat,
          failure: `launcher process tree cleanup failed: ${stopped.stderr?.toString("utf8")}` });
      }
    }
    save();
    // A failed durable checkpoint is a harness failure. Do not start another
    // package with an incomplete report, or mislabel a save error as a UI error.
    await reportWriter.flush();
  }
}

async function main() {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  report.harnessSourceSha256 = Object.fromEntries([
    "tests/verify_next_speed_page.cjs", "tests/observe_next_speed_memory.py",
    "tests/next_speed_atomic_report.cjs", "tests/summarize_next_speed.py",
  ].map((relative) => [relative, sha256(fs.readFileSync(path.join(root, relative)))]));
  report.harnessRuntime = { nodeVersion: process.version, nodeExecutable: process.execPath,
    memoryPython: config.memoryPython || path.join(root, ".venv/Scripts/python.exe") };
  const browser = await chromium.launch({ headless: true });
  try {
    const selected = (config.caseOrder || ["initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16"])
      .map((name) => {
        const frozen = cases.find((item) => item.name === name);
        assert.ok(frozen, `missing frozen case ${name}`);
        return frozen;
      });
    const metrics = config.metrics || ["HTM", "QTM"];
    const repeats = config.repeats ?? 3;
    assert.equal(new Set(selected.map((item) => item.name)).size, selected.length, "duplicate frozen states");
    assert.equal(new Set(metrics).size, metrics.length, "duplicate metrics");
    assert.ok(Number.isInteger(repeats) && repeats >= 1 && repeats <= 3, "only frozen AB/BA/AB repetitions supported");
    if (report.formalMatrix) {
      assert.deepEqual(selected.map((item) => item.name).sort(),
        ["initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16"].sort());
      assert.deepEqual([...metrics].sort(), ["HTM", "QTM"]);
      assert.equal(repeats, 3, "formal acceptance requires all three paired repetitions");
    }
    report.expectedRuns = selected.length * metrics.length * 2 * repeats;
    report.packageIdentity = {};
    for (const label of ["baseline", "current"]) {
      const packageRoot = path.resolve(config.packages[label]);
      assert.ok(fs.existsSync(path.join(packageRoot, report.entry)), "normal package launcher missing");
      report.packageIdentity[label] = { packageRoot, files: {} };
      for (const relative of ["RubicPhotoSolve.exe", "native/htm/build/cube_solver_htm.exe", "native/qtm/build/cube_solver_qtm.exe"]) {
        const actual = [path.join(packageRoot, relative), path.join(packageRoot, "_internal", relative)]
          .find((candidate) => fs.existsSync(candidate));
        assert.ok(actual, `actual packaged executable missing: ${label}/${relative}`);
        report.packageIdentity[label].files[relative] = { path: actual, sha256: sha256(fs.readFileSync(actual)) };
      }
    }
    assert.notEqual(report.packageIdentity.baseline.packageRoot, report.packageIdentity.current.packageRoot,
      "baseline/current must be separate controlled package directories");
    for (const frozen of selected) {
      assert.equal(sha256(frozen.facelets), frozen.facelets_sha256, "frozen Facelets identity changed");
      for (const face of "URFDLB") {
        assert.equal(sha256(fs.readFileSync(path.join(root, frozen.images[face].path))), frozen.images[face].sha256,
          `${frozen.name}/${face} original photo identity changed`);
      }
    }
    report.browserVersion = browser.version();
    save();
    for (let repeat = 0; repeat < repeats; repeat++) {
      const labels = report.order[repeat];
      for (const frozen of selected) {
        for (const metric of metrics) {
          for (const label of labels) await runCase(browser, frozen, metric, label, repeat);
        }
      }
    }
    assert.equal(report.cases.length, report.expectedRuns);
    assert.deepEqual(report.failures, []);
  } finally {
    await browser.close();
    await reportWriter.flush();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
