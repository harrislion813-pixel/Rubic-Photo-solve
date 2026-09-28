"""Rebuild and certify large QTM assets while measuring peak Windows memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_qtm_pdb_build import file_metadata, measured_run


ROOT = Path(__file__).resolve().parents[1]
ASSETS = (
    ("strong", "strong_qtm_v3.pdb", "build-strong-pdb", ["--metric", "QTM"],
     "verify-strong-pdb"),
    ("tail7", "tail_qtm_depth7_v5.pdb", "build-tail-pdb", ["--metric", "QTM", "--depth", "7"],
     "verify-tail-pdb"),
    ("tail8", "tail_qtm_depth8_v5.pdb", "build-tail-pdb", ["--metric", "QTM", "--depth", "8"],
     "verify-tail-pdb"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "native/build/cube_solver.exe")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit-gib", type=float, default=12)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/benchmarks/qtm-large-build-2026-09-28.json")
    args = parser.parse_args()
    if args.threads < 1 or args.memory_limit_gib <= 0:
        parser.error("threads and memory limit must be positive")
    limit = int(args.memory_limit_gib * 1024**3)
    binary = args.binary.resolve()
    output = {"metric": "QTM", "builder": file_metadata(binary),
              "build_info": file_metadata(binary.with_name("build-info.json")),
              "threads": args.threads, "memory_limit_bytes": limit, "assets": {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for key, name, build_command, flags, verify_command in ASSETS:
        published = ROOT / ".cache/native" / name
        temporary = ROOT / ".cache/native" / f"{key}_measurement_20260928.pdb"
        if temporary.exists():
            raise FileExistsError(f"measurement path already exists: {temporary}")
        command = [str(binary), build_command, str(temporary), *flags, "--threads", str(args.threads)]
        if key == "strong":
            command += ["--memory-limit-gib", str(args.memory_limit_gib)]
        if build_command == "build-tail-pdb":
            command += ["--force"]
        build = measured_run(command, limit)
        verification_command = [str(binary), verify_command, str(temporary), "--threads", str(args.threads)]
        verify = measured_run(verification_command, limit)
        built_file = file_metadata(temporary)
        published_file = file_metadata(published)
        if built_file["bytes"] != published_file["bytes"]:
            raise AssertionError(f"new {key} asset has a different size")
        # Parallel Tail insertion may choose different open-addressing slots.
        # Its complete-state verifier, rather than a byte-for-byte hash, is
        # the equivalence certificate for an independently rebuilt Tail.
        if key == "strong" and built_file["sha256"] != published_file["sha256"]:
            raise AssertionError(f"new {key} asset differs from the published verified asset")
        output["assets"][key] = {"build": build, "verify": verify,
                                 "build_command": command, "verify_command": verification_command,
                                 "built_file": built_file, "published_file": published_file,
                                 "same_sha256": built_file["sha256"] == published_file["sha256"]}
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.unlink()
        print(f"{key}: {build['wall_seconds']:.2f}s, peak commit {build['peak_commit_bytes']}", flush=True)


if __name__ == "__main__":
    main()
