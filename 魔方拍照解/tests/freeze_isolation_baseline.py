"""Record the original dirty checkout and reusable local binaries without changing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path


FILES = (
    "README.md",
    "native/build/cube_solver.exe",
    "native/build/build-info.json",
    ".cache/qtm-round2/final/cube_solver.exe",
    ".cache/qtm-round2/final/build-info.json",
    ".cache/native/coordinates_htm_v1.bin",
    ".cache/native/coordinates_dual_v2.bin",
    ".cache/native/corner_htm_v2.pdb",
    ".cache/native/phase1_sym_htm_v2.pdb",
    ".cache/native/tail_depth6_v4.pdb",
    ".cache/native/corner_qtm_v3.pdb",
    ".cache/native/phase1_qtm_v3.pdb",
    ".cache/native/strong_qtm_v4_nibble.pdb",
    ".cache/native/tail_qtm_depth8_v5.pdb",
    ".cache/solver_tables_v3.pkl",
    ".cache/two_by_two_htm_v1.bin",
    ".cache/two_by_two_qtm_v1.bin",
    ".cache/qtm_small_v1.bin",
)


def hash_file(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    original = args.original.resolve()
    files = {
        relative: hash_file(original / relative) if (original / relative).is_file() else None
        for relative in FILES
    }
    manifest = {
        "h0_source": "ae73ca81af1ed077c059f3345377190bf0ce2882",
        "q0_source": "c01d90dcbc449faf3b6128020e71655a0a47960b",
        "original_head": git(original, "rev-parse", "HEAD"),
        "original_status": git(original, "status", "--short"),
        "original_root": str(original),
        "uncommitted_readme_patch": "docs/benchmarks/pre-isolation-readme.patch",
        "user_actual_package": "not provided; local dist files are not assumed to be the user's package",
        "system": platform.platform(),
        "processor": "AMD Ryzen 7 9700X 8-Core Processor",
        "physical_cores": 8,
        "logical_processors": 16,
        "acceptance_threads": 4,
        "compile_modes": {"HTM": "native O3", "QTM": "portable O3"},
        "files": files,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
