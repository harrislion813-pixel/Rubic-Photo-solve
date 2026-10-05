// Reuse the real photo upload driver for recognition-only and solve gates.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn, spawnSync } = require("node:child_process");
const { performance } = require("node:perf_hooks");

const root = path.resolve(__dirname, "..");
const [outputArg, playwrightPath, python = "python", ...options] = process.argv.slice(2);
const value = (name, fallback) => options.find((option) => option.startsWith(`--${name}=`))?.slice(name.length + 3) ?? fallback;
const mode = value("mode", "recognition");
assert.ok(["recognition", "e2e"].includes(mode), `unknown photo verification mode: ${mode}`);
assert.ok(options.every((option) => /^(--mode=|--manifest=|--strict-recognition$)/.test(option)), "unknown photo verification option");
const required = mode === "e2e" || /^(1|true|yes)$/i.test(process.env.REQUIRE_VISION_REAL || "");
const strict = required || options.includes("--strict-recognition");
const output = path.resolve(outputArg || path.join(root, "artifacts/vision/photo-recognition.json"));
const { chromium } = require(playwrightPath || "playwright");
const faces = [..."URFDLB"];
const manifestPath = path.resolve(root, value("manifest", "tests/initial_solver_cases.json"));
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const cases = Array.isArray(manifest) ? manifest : manifest.cases;
assert.ok(cases?.length, "photo manifest must contain cases");
const sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
for (const frozen of cases) {
  assert.ok([2, 3].includes(frozen.cube_size), `${frozen.name}: unsupported cube size`);
  assert.equal(frozen.face_order, "URFDLB");
  assert.equal(frozen.facelets.length, 6 * frozen.cube_size ** 2);
  assert.equal(sha256(frozen.facelets), frozen.facelets_sha256);
  assert.equal(frozen.image_paths.length, 6);
  for (const [index, face] of faces.entries()) {
    const relative = frozen.image_paths[index];
    const record = frozen.images[face];
    assert.equal(record.path, relative);
    const bytes = fs.readFileSync(path.resolve(root, relative));
    assert.equal(sha256(bytes), record.sha256, `${frozen.name}/${face}: fixture hash`);
    assert.equal(bytes.length, record.bytes, `${frozen.name}/${face}: fixture size`);
  }
}
const report = {
  mode, strictRecognition: strict,
  method: "Real page file uploads, actual Canvas and backend detection, perspective sampling and production color classification. E2E mode submits uncorrected recognition output and independently replays returned formulas; it does not require shortest proof.",
  recordedAt: new Date().toISOString(),
  sourceSha256: Object.fromEntries(["web/app.js", "web/color.js", "web/index.html", "cube_app/vision.py", "cube_app/detection.py", "server.py", "cube_app/service/dependencies.py", "cube_app/service/http_api.py", "cube_app/service/jobs.py", "cube_app/service/solving.py"].map((relative) => [relative, sha256(fs.readFileSync(path.join(root, relative)))])),
  caseManifestSha256: sha256(fs.readFileSync(manifestPath)),
  cases: [], solveRequests: 0,
};
const save = () => fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");

async function solveAndReplay(page, context, url, frozen, result) {
  await page.locator("#metricSelect").selectOption("HTM");
  await page.locator(".advanced-panel > summary").click();
  await page.locator("#timeoutInput").fill("30");
  const responsePromise = page.waitForResponse((response) =>
    response.url() === url + "api/solve" && response.request().method() === "POST", { timeout: 120000 });
  await page.locator("#solveBtn").click();
  const response = await responsePromise;
  const request = response.request().postDataJSON();
  assert.equal(request.facelets, result.automaticFacelets, "solve must receive actual uncorrected page facelets");
  assert.equal(request.cube_size, frozen.cube_size);
  assert.equal(request.metric, "HTM");
  const initial = await response.json();
  assert.equal(response.ok(), true);
  assert.equal(initial.ok, true, JSON.stringify(initial));
  result.solveRequest = request;
  result.initial = initial;
  const formulas = [];
  const collect = (formula) => {
    if (formula && Array.isArray(formula.moves) && Number.isInteger(formula.depth ?? formula.cost)) formulas.push(formula);
  };
  collect(initial);
  const deadline = Date.now() + 120000;
  try {
    if (initial.job_id) {
      do {
        const poll = await context.request.get(`${url}api/solve/${initial.job_id}`);
        assert.equal(poll.ok(), true);
        const job = await poll.json();
        result.snapshot = job;
        assert.notEqual(job.status, "error", JSON.stringify(job));
        assert.ok(!job.fallback_reason && !job.candidate_error, JSON.stringify(job));
        collect(job.result);
        collect(job.candidate_result);
        for (const event of job.timing_events || []) collect(event);
        if (formulas.length) break;
        assert.ok(!["complete", "timeout", "cancelled", "budget_exhausted"].includes(job.status), "job ended without a valid candidate");
        assert.ok(Date.now() < deadline, "photo solve returned no candidate within the harness deadline");
        await new Promise((resolve) => setTimeout(resolve, 100));
      } while (true);
    }
    assert.ok(formulas.length, "photo solve must return at least one formula");
    const replay = spawnSync(python, ["-X", "utf8", path.join(root, "tests/replay_photo_solution.py")], {
      cwd: root, windowsHide: true, encoding: "utf8", timeout: 30000,
      input: JSON.stringify({ cube_size: frozen.cube_size, facelets: result.automaticFacelets, formulas }),
    });
    assert.equal(replay.status, 0, replay.stderr || replay.error?.message || replay.stdout);
    result.replay = JSON.parse(replay.stdout);
    await page.waitForFunction(() => {
      const text = document.querySelector("#solutionText").textContent;
      return /[URFDLB]/.test(text) || text.includes("已复原");
    });
  } finally {
    if (initial.job_id) {
      const cancelled = await context.request.post(`${url}api/solve/${initial.job_id}/cancel`, { data: {} });
      assert.equal(cancelled.ok(), true);
    }
  }
}

async function main() {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  // An OS-assigned port avoids disturbing another local launcher/service.
  const preflight = mode === "e2e" ? "from cube_app.solvers.htm.native import native_solver_available; assert native_solver_available(), 'required HTM native binary/PDB assets missing'; " : "";
  const server = spawn(python, ["-u", "-c", preflight + "import server; s=server.ExclusiveThreadingHTTPServer((server.HOST,0),server.AppHandler); print('http://127.0.0.1:%d/'%s.server_address[1],flush=True); s.serve_forever()"], {
    cwd: root, windowsHide: true, env: { ...process.env, PYTHONUTF8: "1" },
  });
  const logs = [];
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("photo-only server startup timeout")), 20000);
      server.stdout.on("data", (data) => {
        const match = data.toString("utf8").match(/http:\/\/127\.0\.0\.1:\d+\//);
        if (match) { clearTimeout(timeout); resolve(match[0]); }
      });
      server.stderr.on("data", (data) => logs.push(data.toString("utf8")));
      server.once("error", reject);
      server.once("exit", (code) => reject(new Error(`photo-only server exited ${code}: ${logs.join("")}`)));
    });
    report.url = url;
    browser = await chromium.launch({ headless: true });
    report.browserVersion = browser.version();
    for (const frozen of cases) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      const page = await context.newPage();
      const result = { name: frozen.name, cubeSize: frozen.cube_size, referenceFacelets: frozen.facelets, referenceFaceletsSha256: frozen.facelets_sha256, detectionResponses: {}, pageErrors: [] };
      report.cases.push(result);
      const pending = new Set();
      page.on("pageerror", (error) => result.pageErrors.push(error.message));
      page.on("request", (request) => {
        if (request.url().includes("/api/solve")) report.solveRequests += 1;
      });
      if (mode === "recognition") await page.route("**/api/solve**", (route) => route.abort());
      let currentFace;
      page.on("response", (response) => {
        if (!response.url().endsWith("/api/detect")) return;
        const face = currentFace;
        const task = response.json().then((data) => { result.detectionResponses[face] = data; });
        pending.add(task);
        task.finally(() => pending.delete(task));
      });
      try {
        await page.goto(url, { waitUntil: "networkidle" });
        await page.locator("#cubeSizeSelect").selectOption(String(frozen.cube_size));
        const start = performance.now();
        for (const [index, face] of faces.entries()) {
          currentFace = face;
          await page.locator(`[data-face="${face}"] .file-input`).setInputFiles(path.join(root, frozen.image_paths[index]));
          await page.waitForFunction((face) => !document.querySelector(`[data-face="${face}"] .adjust-region`).disabled, face);
          await Promise.all([...pending]);
          assert.equal(result.detectionResponses[face]?.detected, true, `${frozen.name}/${face} backend detection`);
        }
        result.identificationSeconds = (performance.now() - start) / 1000;
        result.automaticFacelets = await page.locator("#faceletsText").inputValue();
        result.automaticFaceletsSha256 = sha256(result.automaticFacelets);
        result.automaticMatchesReference = result.automaticFacelets === frozen.facelets;
        if (strict) assert.equal(result.automaticFacelets, frozen.facelets, `${frozen.name}: automatic recognition must match the human reference before any correction`);
        result.statusBeforeCorrection = await page.locator("#statusText").textContent();
        result.stickerConfidence = await page.evaluate(() => Object.fromEntries([..."URFDLB"].map((face) => [face,
          [...document.querySelectorAll(`[data-face="${face}"] .sticker`)].map((sticker) => ({ color: sticker.dataset.color, low: sticker.classList.contains("low-confidence"), title: sticker.title }))])));
        const canvasImages = await page.evaluate(() => Object.fromEntries([..."URFDLB"].map((face) => [face, document.querySelector(`[data-face="${face}"] canvas.preview`).toDataURL("image/png").split(",")[1]])));
        result.previewPaths = {};
        for (const face of faces) {
          const name = `${frozen.name}-${face}-browser-preview.png`;
          fs.writeFileSync(path.join(path.dirname(output), name), Buffer.from(canvasImages[face], "base64"));
          result.previewPaths[face] = name;
        }
        result.manualCorrections = [];
        const faceSize = frozen.cube_size ** 2;
        for (let index = 0; !strict && index < 6 * faceSize; index += 1) {
          const actual = result.automaticFacelets[index], expected = frozen.facelets[index];
          if (actual === expected) continue;
          const face = faces[Math.floor(index / faceSize)], stickerIndex = index % faceSize;
          if (frozen.cube_size === 3) assert.notEqual(stickerIndex, 4, "center color cannot be manually changed");
          const cycles = (faces.indexOf(expected) - faces.indexOf(actual) + faces.length) % faces.length;
          const sticker = page.locator(`[data-face="${face}"] .sticker[data-index="${stickerIndex}"]`);
          for (let step = 0; step < cycles; step += 1) await sticker.click();
          result.manualCorrections.push({ face, stickerIndex, row: Math.floor(stickerIndex / frozen.cube_size) + 1, column: stickerIndex % frozen.cube_size + 1, automatic: actual, reference: expected, clicks: cycles });
        }
        result.correctedFacelets = await page.locator("#faceletsText").inputValue();
        result.rotationCorrections = [];
        if (mode === "e2e") await solveAndReplay(page, context, url, frozen, result);
        result.finalScreenshot = `${frozen.name}-photo-page.png`;
        await page.screenshot({ path: path.join(path.dirname(output), result.finalScreenshot), fullPage: true });
        assert.equal(result.correctedFacelets, frozen.facelets);
        assert.deepEqual(result.pageErrors, []);
        console.log(JSON.stringify({ name: result.name, automaticMatchesReference: result.automaticMatchesReference, corrections: result.manualCorrections.length }));
      } catch (error) {
        result.failure = error.stack;
        await page.screenshot({ path: path.join(path.dirname(output), `${frozen.name}-failure.png`), fullPage: true }).catch(() => {});
        throw error;
      } finally {
        await context.close();
        save();
      }
    }
    if (mode === "recognition") assert.equal(report.solveRequests, 0);
    else assert.ok(report.solveRequests >= cases.length, "each case must execute a real solve request");
    report.passed = true;
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null && server.signalCode === null) {
      if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(server.pid), "/T", "/F"], { windowsHide: true });
      else server.kill();
    }
    await new Promise((resolve) => server.exitCode !== null || server.signalCode !== null ? resolve() : server.once("exit", resolve));
    report.serverStopped = true;
    report.serverLog = logs;
    save();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
