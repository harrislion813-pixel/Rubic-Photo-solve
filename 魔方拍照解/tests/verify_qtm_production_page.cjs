// Browser acceptance uses the normal launcher and never overrides solver defaults.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { performance } = require("node:perf_hooks");

const [packageRoot, output, playwrightPath] = process.argv.slice(2);
const { chromium } = require(playwrightPath || "playwright");
const root = path.resolve(__dirname, "..");
const cases = JSON.parse(fs.readFileSync(path.join(root, "tests/initial_solver_cases.json"), "utf8"));
const report = { entry: "启动魔方求解器.cmd", solverOverrides: {}, timeout: 30, cases: [] };
const save = () => fs.writeFileSync(output, JSON.stringify(report, null, 2));
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function start() {
  const env = { ...process.env, CUBE_NO_BROWSER: "1", PYTHONUTF8: "1" };
  for (const key of Object.keys(env)) {
    if (/^CUBE_(QTM|NATIVE)_/.test(key) || key === "PYTHONPATH") delete env[key];
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
  const until = performance.now() + 30000;
  while (!url && processHandle.exitCode === null && performance.now() < until) await pause(50);
  if (!url) {
    spawnSync("taskkill.exe", ["/PID", String(processHandle.pid), "/T", "/F"], { windowsHide: true });
    throw new Error(`normal launcher failed: ${logs.join("")}`);
  }
  return { processHandle, url, logs };
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

async function runCase(browser, frozen) {
  const launch = await start();
  const result = { name: frozen.name, facelets: frozen.facelets, url: launch.url,
    newProcess: true, events: [], pageErrors: [], logs: launch.logs };
  report.cases.push(result);
  save();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const pending = new Set();
  let started;
  page.on("pageerror", (error) => result.pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().endsWith("/api/solve") && request.method() === "POST") {
      started = performance.now();
      result.request = request.postDataJSON();
    }
  });
  page.on("response", (response) => {
    if (!/\/api\/solve(?:\/[^/]+)?$/.test(response.url())) return;
    const task = (async () => {
      const seconds = (performance.now() - started) / 1000;
      const data = await response.json();
      result.events.push({ seconds, data });
      if (data.job_id) result.jobId = data.job_id;
      if (["complete", "timeout", "cancelled", "error", "budget_exhausted"].includes(data.status)) {
        result.final = data;
      }
      save();
    })().catch((error) => result.pageErrors.push(error.message));
    pending.add(task);
    task.finally(() => pending.delete(task));
  });
  try {
    await page.goto(launch.url, { waitUntil: "networkidle" });
    await page.waitForFunction(() => !document.querySelector('#metricSelect option[value="QTM"]').disabled);
    for (const [index, face] of [..."URFDLB"].entries()) {
      await page.locator(`[data-face="${face}"] .file-input`).setInputFiles(path.join(root, frozen.image_paths[index]));
      await page.waitForFunction((face) => !document.querySelector(`[data-face="${face}"] .adjust-region`).disabled, face);
    }
    await page.locator(".advanced-panel > summary").click();
    await page.locator("#faceletsText").fill(frozen.facelets);
    await page.locator("#metricSelect").selectOption("QTM");
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
    result.desktopScreenshot = path.join(path.dirname(output), `${frozen.name}-desktop.png`);
    await page.screenshot({ path: result.desktopScreenshot, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    result.mobile = await inspectLayout(page);
    result.mobileScreenshot = path.join(path.dirname(output), `${frozen.name}-mobile.png`);
    await page.screenshot({ path: result.mobileScreenshot, fullPage: true });
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
    console.log(JSON.stringify({ name: result.name, status: result.final?.status,
      cost: result.final?.result?.depth, pageWallSeconds: result.pageWallSeconds,
      firstCandidate: result.afterCleanup?.first_candidate_seconds,
      strongReady: result.afterCleanup?.strong_ready_seconds,
      strongAdopted: result.afterCleanup?.strong_adopted_seconds }));
  } catch (error) {
    result.failure = error.stack;
    throw error;
  } finally {
    save();
    await context.close();
    // Kill only this launcher's process tree, including its paused resident.
    spawnSync("taskkill.exe", ["/PID", String(launch.processHandle.pid), "/T", "/F"], { windowsHide: true });
    await new Promise((resolve) => launch.processHandle.exitCode !== null ? resolve() : launch.processHandle.once("exit", resolve));
    result.processTreeStopped = true;
    save();
  }
}

async function main() {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const frozen of cases) await runCase(browser, frozen);
  } finally {
    await browser.close();
    save();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
