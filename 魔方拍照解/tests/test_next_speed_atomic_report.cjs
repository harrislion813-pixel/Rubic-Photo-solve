const assert = require("node:assert/strict");
const fs = require("node:fs");
const promises = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { test } = require("node:test");
const { AtomicReportWriter } = require("./next_speed_atomic_report.cjs");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const cleanup = (directory) => {
  const resolved = path.resolve(directory);
  assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
  assert.ok(path.basename(resolved).startsWith("next-speed-report-"));
  fs.rmSync(resolved, { recursive: true, force: true });
};

test("Windows read-sharing lock retries without blocking response timestamps or complete JSON readers", async () => {
  assert.equal(process.platform, "win32", "this gate requires actual Windows sharing semantics");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "next-speed-report-"));
  const filename = path.join(directory, "report.json");
  fs.writeFileSync(filename, JSON.stringify({ initial: true }));
  const escaped = filename.replaceAll("'", "''");
  const locker = spawn("powershell.exe", ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
    `$lockedReport = [System.IO.File]::Open('${escaped}', [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read); [Console]::WriteLine('locked'); Start-Sleep -Milliseconds 300; $lockedReport.Dispose()`],
  { windowsHide: true });
  let stderr = "";
  locker.stderr.on("data", (data) => { stderr += data; });
  let ticks = 0, reads = 0;
  const readErrors = [];
  let timer;
  try {
    await new Promise((resolve, reject) => {
      locker.stdout.on("data", (data) => { if (data.toString().includes("locked")) resolve(); });
      locker.once("error", reject);
      locker.once("exit", (code) => reject(new Error(`reader exited ${code}: ${stderr}`)));
    });
    timer = setInterval(() => {
      ticks += 1;
      try { JSON.parse(fs.readFileSync(filename, "utf8")); reads += 1; }
      catch (error) { readErrors.push(error.message); }
    }, 5);
    const evidence = { events: [{ seconds: 0.125, data: { status: "candidate", depth: 24 } }], pageErrors: [] };
    const writer = new AtomicReportWriter(filename, () => evidence, { retryMs: 10 });
    writer.requestSave();
    await pause(50);
    evidence.events.push({ seconds: 0.25, data: { status: "complete", depth: 18 } });
    writer.requestSave();
    await writer.flush();
    const saved = JSON.parse(fs.readFileSync(filename, "utf8"));
    assert.equal(saved.events.length, 2);
    assert.deepEqual(saved.events.map((frame) => frame.seconds), [0.125, 0.25]);
    assert.deepEqual(saved.pageErrors, []);
    assert.ok(writer.diagnostics().sharingRetries > 0, "real read lock did not exercise rename retries");
    assert.ok(ticks > 2 && reads > 2, "sharing retry blocked the event loop");
    assert.deepEqual(readErrors, [], "a reader observed truncated JSON during an atomic replacement");
    assert.deepEqual(fs.readdirSync(directory), ["report.json"]);
  } finally {
    if (timer) clearInterval(timer);
    if (locker.exitCode === null) locker.kill();
    await new Promise((resolve) => locker.exitCode !== null ? resolve() : locker.once("exit", resolve));
    cleanup(directory);
  }
});

test("final replacement failure rejects and preserves the complete uncommitted checkpoint", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "next-speed-report-fatal-"));
  const filename = path.join(directory, "report.json");
  const evidence = { events: [{ seconds: 2, data: { status: "timeout" } }], failures: [] };
  const forced = { ...promises, rename: async () => { const error = new Error("forced read sharing lock"); error.code = "EBUSY"; throw error; } };
  const writer = new AtomicReportWriter(filename, () => evidence,
    { fs: forced, retryMs: 2, retryBudgetMs: 10 });
  try {
    await assert.rejects(writer.flush(), /unsaved complete checkpoint retained/);
    const failure = writer.diagnostics().failures[0];
    assert.deepEqual(JSON.parse(fs.readFileSync(failure.recoverableTemporaryFile, "utf8")), evidence);
    assert.equal(fs.existsSync(filename), false);
  } finally {
    cleanup(directory);
  }
});
