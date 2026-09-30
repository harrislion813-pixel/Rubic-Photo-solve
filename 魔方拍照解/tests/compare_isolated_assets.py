"""Check old and isolated unpacked packages use identical PDB bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


HTM_NAMES = ("corner_htm_v2.pdb", "phase1_sym_htm_v2.pdb", "tail_depth6_v4.pdb")
QTM_NAMES = HTM_NAMES + (
    "corner_qtm_v3.pdb", "phase1_qtm_v3.pdb", "strong_qtm_v4_nibble.pdb",
    "tail_qtm_depth8_v5.pdb",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare(old_package: Path, new_package: Path, metric: str) -> dict:
    names = HTM_NAMES if metric == "HTM" else QTM_NAMES
    manifest = json.loads((new_package / "asset-manifest.json").read_text(encoding="utf-8"))
    old_root = old_package / ".cache" / "native"
    new_relative_root = "assets/htm/v1" if metric == "HTM" else "assets/qtm/v1"
    result = {}
    for name in names:
        old_path = old_root / name
        new_relative = f"{new_relative_root}/{name}"
        expected = manifest["files"][new_relative]
        old_hash = sha256(old_path)
        result[name] = {
            "old_path": str(old_path), "new_path": str(new_package / new_relative),
            "old_bytes": old_path.stat().st_size, "new_bytes": expected["bytes"],
            "old_sha256": old_hash, "new_sha256": expected["sha256"],
            "identical": old_hash.lower() == expected["sha256"].lower()
            and old_path.stat().st_size == expected["bytes"],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("h0", "h1", "q0", "q1"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packages = {name: getattr(args, name).resolve() for name in ("h0", "h1", "q0", "q1")}
    result = {
        "packages": {name: str(path) for name, path in packages.items()},
        "HTM": compare(packages["h0"], packages["h1"], "HTM"),
        "QTM": compare(packages["q0"], packages["q1"], "QTM"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, package in (("HtmFull", packages["h1"]), ("QtmStrong", packages["q1"])):
        shutil.copyfile(package / "asset-manifest.json", args.output.parent / f"{name}-asset-manifest.json")
    if not all(item["identical"] for metric in ("HTM", "QTM") for item in result[metric].values()):
        raise AssertionError("baseline and isolated packages differ in selected PDB assets")
    print("HTM matched assets:", len(result["HTM"]), "QTM matched assets:", len(result["QTM"]))


if __name__ == "__main__":
    main()
