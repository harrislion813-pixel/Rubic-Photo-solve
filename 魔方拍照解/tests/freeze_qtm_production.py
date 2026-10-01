"""Freeze source, executable and existing assets before a bounded QTM comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
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
    parser.add_argument("--save-binary", type=Path)
    args = parser.parse_args()
    binary = ROOT / "native/qtm/build/cube_solver_qtm.exe"
    paths = [binary, ROOT / "native/qtm/build/build-info.json", ROOT / "asset-manifest.json"]
    paths += sorted((ROOT / "native/qtm").glob("src/*"))
    paths += sorted((ROOT / "native/qtm").glob("include/*"))
    paths += sorted((ROOT / "assets/qtm/v1").glob("*.pdb"))
    paths += [ROOT / "native/htm/build/cube_solver_htm.exe", ROOT / "native/htm/build/build-info.json"]
    paths += sorted((ROOT / "native/htm").glob("src/*"))
    paths += sorted((ROOT / "native/htm").glob("include/*"))
    report = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip(),
        "system": platform.platform(),
        "files": {str(path.relative_to(ROOT)): identity(path) if path.is_file() else None for path in paths},
    }
    if args.save_binary:
        args.save_binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, args.save_binary)
        report["saved_binary"] = str(args.save_binary.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
