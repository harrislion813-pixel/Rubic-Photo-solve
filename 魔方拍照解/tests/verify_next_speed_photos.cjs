// Upload frozen original photos through the real page; never start a solver.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const { performance } = require("node:perf_hooks");

const root = path.resolve(__dirname, "..");
const [outputArg, playwrightPath, python = "python"] = process.argv.slice(2);
const output = path.resolve(outputArg || path.join(root, "docs/benchmarks/next-speed-2026-10-02/photo-recognition.json"));
const { chromium } = require(playwrightPath || "playwright");
const faces = [..."URFDLB"];
const cases = JSON.parse(fs.readFileSync(path.join(root, "tests/initial_solver_cases.json"), "utf8"));
const sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
const report = {
  method: "Original photos uploaded into normal page file inputs; actual browser Canvas resize/JPEG detection, perspective rectification, patch sampling and web/color.js classification. No solve requests.",
  recordedAt: new Date().toISOString(),
  sourceSha256: Object.fromEntries(["web/app.js", "web/color.js", "web/index.html", "cube_app/vision.py", "cube_app/detection.py"].map((relative) => [relative, sha256(fs.readFileSync(path.join(root, relative)))])),
  caseManifestSha256: sha256(fs.readFileSync(path.join(root, "tests/initial_solver_cases.json"))),
  cases: [], solveRequests: 0,
};
const save = () => fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");

async function main() {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  // An OS-assigned port avoids disturbing another local launcher/service.
  const server = spawn(python, ["-u", "-c", "import server; s=server.ExclusiveThreadingHTTPServer((server.HOST,0),server.AppHandler); print('http://127.0.0.1:%d/'%s.server_address[1],flush=True); s.serve_forever()"], {
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
      const result = { name: frozen.name, referenceFacelets: frozen.facelets, referenceFaceletsSha256: frozen.facelets_sha256, detectionResponses: {}, pageErrors: [] };
      report.cases.push(result);
      const pending = new Set();
      page.on("pageerror", (error) => result.pageErrors.push(error.message));
      await page.route("**/api/solve**", async (route) => {
        report.solveRequests += 1;
        await route.abort();
      });
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
        for (let index = 0; index < 54; index += 1) {
          const actual = result.automaticFacelets[index], expected = frozen.facelets[index];
          if (actual === expected) continue;
          const face = faces[Math.floor(index / 9)], stickerIndex = index % 9;
          assert.notEqual(stickerIndex, 4, "center color cannot be manually changed");
          const cycles = (faces.indexOf(expected) - faces.indexOf(actual) + faces.length) % faces.length;
          const sticker = page.locator(`[data-face="${face}"] .sticker[data-index="${stickerIndex}"]`);
          for (let step = 0; step < cycles; step += 1) await sticker.click();
          result.manualCorrections.push({ face, stickerIndex, row: Math.floor(stickerIndex / 3) + 1, column: stickerIndex % 3 + 1, automatic: actual, reference: expected, clicks: cycles });
        }
        result.correctedFacelets = await page.locator("#faceletsText").inputValue();
        result.automaticMatchesReference = result.automaticFacelets === frozen.facelets;
        result.rotationCorrections = [];
        result.finalScreenshot = `${frozen.name}-photo-page.png`;
        await page.screenshot({ path: path.join(path.dirname(output), result.finalScreenshot), fullPage: true });
        assert.equal(result.correctedFacelets, frozen.facelets);
        assert.deepEqual(result.pageErrors, []);
        console.log(JSON.stringify({ name: result.name, automaticMatchesReference: result.automaticMatchesReference, corrections: result.manualCorrections.length }));
      } catch (error) {
        result.failure = error.stack;
        throw error;
      } finally {
        await context.close();
        save();
      }
    }
    assert.equal(report.solveRequests, 0);
    report.passed = true;
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise((resolve) => server.exitCode !== null || server.signalCode !== null ? resolve() : server.once("exit", resolve));
    report.serverStopped = true;
    report.serverLog = logs;
    save();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
