"""Verify the full runtime asset set of a portable or source installation."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HTM = {
    "native/htm/build/cube_solver_htm.exe",
    "assets/htm/v1/corner_htm_v2.pdb",
    "assets/htm/v1/phase1_sym_htm_v2.pdb",
    "assets/htm/v1/tail_depth6_v4.pdb",
    ".cache/htm/solver_tables_v3.pkl",
    ".cache/htm/two_by_two_htm_v1.bin",
    ".cache/htm/coordinates_htm_v1.bin",
    ".cache/htm/phase1_symmetry_htm_v1.bin",
    ".cache/htm/phase2_htm_v1.bin",
}
QTM = {
    "native/qtm/build/cube_solver_qtm.exe",
    "assets/qtm/v1/corner_htm_v2.pdb",
    "assets/qtm/v1/phase1_sym_htm_v2.pdb",
    "assets/qtm/v1/tail_depth6_v4.pdb",
    "assets/qtm/v1/corner_qtm_v3.pdb",
    "assets/qtm/v1/phase1_qtm_v3.pdb",
    "assets/qtm/v1/strong_qtm_v4_nibble.pdb",
    "assets/qtm/v1/tail_qtm_depth8_v5.pdb",
    ".cache/qtm/solver_tables_v3.pkl",
    ".cache/qtm/qtm_small_v1.bin",
    ".cache/qtm/two_by_two_qtm_v1.bin",
    ".cache/qtm/coordinates_dual_v2.bin",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "asset-manifest.json").read_text(encoding="utf-8-sig"))
    profile = manifest["profile"]
    if profile not in {"HtmFull", "QtmStrong"}:
        raise ValueError(f"unknown profile: {profile}")
    expected = HTM | (QTM if profile == "QtmStrong" else set())
    if set(manifest["files"]) != expected:
        raise ValueError("runtime manifest does not contain exactly the full selected asset set")
    version_file = root / "VERSION.txt"
    if version_file.exists() and version_file.read_text(encoding="utf-8").strip() != manifest["app_version"]:
        raise ValueError("VERSION.txt differs from the asset manifest")
    for relative, record in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"asset escapes the installation directory: {relative}")
        if not path.is_file() or path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ValueError(f"asset verification failed: {relative}")
    print(f"verified: {manifest['app_version']} / {profile} / {len(expected)} assets")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    verify(parser.parse_args().root)
