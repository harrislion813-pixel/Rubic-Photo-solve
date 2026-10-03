// Coalesced asynchronous checkpoints never write through a reader's open file.
const fs = require("node:fs/promises");
const path = require("node:path");
const { performance } = require("node:perf_hooks");

class AtomicReportWriter {
  constructor(filename, value, options = {}) {
    this.filename = path.resolve(filename);
    this.value = value;
    this.fs = options.fs || fs;
    this.retryMs = options.retryMs ?? 25;
    this.retryBudgetMs = options.retryBudgetMs ?? 5000;
    this.requested = 0;
    this.committed = 0;
    this.pending = null;
    this.error = null;
    this.retries = 0;
    this.failures = [];
  }

  diagnostics() {
    return { method: "same-directory temporary file plus asynchronous atomic rename",
      nonblockingRetryMs: this.retryMs, retryBudgetMs: this.retryBudgetMs,
      sharingRetries: this.retries, failures: this.failures };
  }

  requestSave() {
    this.requested += 1;
    this._begin();
  }

  _begin() {
    if (!this.pending) {
      this.error = null;
      // Handle background failures here. They belong to persistence, never to
      // pageerror/response parsing, and flush() makes them fatal at checkpoints.
      this.pending = this._drain().catch((error) => {
        this.error = error;
        this.failures.push({ code: error.code, message: error.message,
          recoverableTemporaryFile: error.recoverableTemporaryFile });
      }).finally(() => {
        this.pending = null;
        // A request can arrive after _drain's final loop check but before this
        // promise settles. Drain that generation without waiting for another
        // response, and without turning a recovered save into a false failure.
        if (!this.error && this.committed < this.requested) this._begin();
      });
    }
  }

  async _drain() {
    await this.fs.mkdir(path.dirname(this.filename), { recursive: true });
    while (this.committed < this.requested) {
      const generation = this.requested;
      const temporary = path.join(path.dirname(this.filename),
        `.${path.basename(this.filename)}.${process.pid}.${generation}.uncommitted.json`);
      const serialized = JSON.stringify(this.value(), null, 2) + "\n";
      await this.fs.writeFile(temporary, serialized, "utf8");
      const started = performance.now();
      while (true) {
        try {
          await this.fs.rename(temporary, this.filename);
          break;
        } catch (error) {
          const sharingError = ["EBUSY", "EPERM", "EACCES", "UNKNOWN"].includes(error.code);
          if (!sharingError || performance.now() - started >= this.retryBudgetMs) {
            // Preserve the complete serialized checkpoint for recovery when a
            // reader or permissions prevent replacement of the main report.
            error.recoverableTemporaryFile = temporary;
            error.message += `; unsaved complete checkpoint retained at ${temporary}`;
            throw error;
          }
          this.retries += 1;
          await new Promise((resolve) => setTimeout(resolve, this.retryMs));
        }
      }
      this.committed = generation;
    }
  }

  async flush() {
    this.requestSave();
    while (this.pending) await this.pending;
    if (this.error) throw this.error;
    if (this.committed !== this.requested) throw new Error("report checkpoint did not commit the latest record");
  }
}

module.exports = { AtomicReportWriter };
