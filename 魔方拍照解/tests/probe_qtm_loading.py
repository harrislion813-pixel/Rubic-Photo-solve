"""Compare complete v4 validation without running any proof or candidate search."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from test_native_qtm import Service, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=(4, 8), default=4)
    args = parser.parse_args()
    report = {"binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
              "threads": args.threads, "scope": "complete validation; OS file cache not cleared; no search",
              "runs": []}
    for mode in ("legacy", "split", "fused"):
        command = ["--qtm-pdb", ROOT / "assets/qtm/v1/corner_qtm_v3.pdb",
                   "--qtm-phase1-pdb", ROOT / "assets/qtm/v1/phase1_qtm_v3.pdb",
                   "--strong-pdb", ROOT / "assets/qtm/v1/strong_qtm_v4_nibble.pdb",
                   "--loader-threads", str(args.threads), f"--strong-validation={mode}", "--asset-loading=eager"]
        started = time.perf_counter()
        with Service(args.binary.resolve(), *command) as service:
            ready = service.event("ready")
            assert ready["assets"]["QTM"]["profile"] == "strong-no-tail"
            run = {"mode": mode, "wall_seconds": time.perf_counter() - started,
                   "command": list(map(str, command)), "ready": ready}
            report["runs"].append(run)
            print(json.dumps({"mode": mode, **{key: ready[key] for key in (
                "strong_initialization_seconds", "strong_verification_seconds",
                "strong_checksum_worker_seconds", "strong_nibble_worker_seconds"
            )}}), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
