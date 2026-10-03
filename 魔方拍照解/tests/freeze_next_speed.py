"""Freeze the actual two-engine checkout before next-speed experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=15)
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    if snapshot.exists():
        parser.error("snapshot already exists; never overwrite a frozen baseline")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    paths = {ROOT / name for name in tracked if name and (ROOT / name).is_file()}
    for engine in ("htm", "qtm"):
        paths.update((ROOT / f"native/{engine}/build").glob("*"))
        paths.update((ROOT / f"assets/{engine}/v1").glob("*.pdb"))
        paths.update((ROOT / f".cache/{engine}").glob("*"))
    paths.add(ROOT / "asset-manifest.json")
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip(),
        "system": platform.platform(), "logical_cpus": os.cpu_count(), "threads": args.threads,
        "snapshot": str(snapshot), "files": {},
        "experiment_order": [["baseline", "current"], ["current", "baseline"], ["baseline", "current"]],
        "fixed_layer_timeout_seconds": 5, "request_timeout_seconds": 30,
        "initial_order": [1, 12, 2, 5, 8, 16],
        "gates": {"same_tree_min_improvement": 0.05, "max_regression": 0.05,
                  "h1_delivery_target": 0.20, "engine_par2_target": 0.15},
        "cache_condition": "new process, warm OS file cache; disk cache is not cleared",
    }
    for path in sorted(paths):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        report["files"][relative.as_posix()] = identity(path)
        # Keep immutable copies of all source and executables. Large tables remain
        # shared read-only inputs, identified separately by their content hashes.
        if relative.parts[0] not in {"assets", ".cache"}:
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
