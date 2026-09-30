"""Audit native worker frames; early H0 runner metadata hardcoded four threads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FILES = (
    "htm-h0-real.json", "htm-h1-real-release.json",
    "qtm-q0-real.json", "qtm-q1-real-release.json",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    output = {}
    for name in FILES:
        source = json.loads((args.directory / name).read_text(encoding="utf-8"))
        cases = []
        for run in source["runs"]:
            frame = run["final"].get("progress") or {}
            workers = frame.get("workers")
            cases.append({"name": run["name"], "observed_worker_frames": len(workers) if workers else None})
        output[name] = {"recorded_runner_threads_field": source.get("threads"), "cases": cases}
    if any(case["observed_worker_frames"] != 15
           for item in output.values() for case in item["cases"]):
        raise AssertionError("some real-package native worker frames do not show 15 threads")
    destination = args.directory / "real-thread-audit.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All eight real-package result frames show 15 workers")


if __name__ == "__main__":
    main()
