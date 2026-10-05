"""Validate the selected release profile and emit its immutable asset manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from source_layout import application_sources

HTM = (
    "native/htm/build/cube_solver_htm.exe",
    "assets/htm/v1/corner_htm_v2.pdb",
    "assets/htm/v1/phase1_sym_htm_v2.pdb",
    "assets/htm/v1/tail_depth6_v4.pdb",
    ".cache/htm/solver_tables_v3.pkl",
    ".cache/htm/two_by_two_htm_v1.bin",
    ".cache/htm/coordinates_htm_v1.bin",
    ".cache/htm/phase1_symmetry_htm_v1.bin",
    ".cache/htm/phase2_htm_v1.bin",
)
QTM = (
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
)


def _u32(header: bytes, offset: int) -> int:
    return struct.unpack_from("<I", header, offset)[0]


def inspect(path: Path) -> dict:
    name = path.name
    if not name.endswith(".pdb"):
        return {}
    with path.open("rb") as stream:
        header = stream.read(80)
    if name.startswith("tail_"):
        if header[:8] != b"RCTAIL1\0":
            raise ValueError(f"bad tail magic: {path}")
        metric, depth = _u32(header, 16), _u32(header, 20)
        expected = 2 if name.startswith("tail_qtm_") else 1
        if metric != expected or depth != (8 if expected == 2 else 6):
            raise ValueError(f"tail metric/depth mismatch: {path}")
        return {"metric": "QTM" if metric == 2 else "HTM", "depth": depth,
                "format_version": _u32(header, 8)}
    if header[:8] != b"RCPDB01\0":
        raise ValueError(f"bad PDB magic: {path}")
    version = _u32(header, 8)
    metric = _u32(header, 16)
    expected = 2 if "qtm" in name else 1
    if metric != expected:
        raise ValueError(f"PDB metric mismatch: {path}")
    flags = _u32(header, 40 if version in (3, 4) else 32)
    if not flags & 1:
        raise ValueError(f"incomplete PDB: {path}")
    result = {"metric": "QTM" if metric == 2 else "HTM", "format_version": version,
              "complete": True}
    if version in (3, 4):
        result["coordinate_version"] = _u32(header, 24)
        result["coverage_depth"] = _u32(header, 32)
    return result


def metadata(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest(), **inspect(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", choices=("HtmFull", "QtmStrong"), required=True)
    parser.add_argument("--write", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    paths = HTM + (QTM if args.profile == "QtmStrong" else ())
    files = {}
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.stat().st_size < 1024:
            raise FileNotFoundError(f"missing release asset: {path}")
        files[relative] = metadata(path)
    sys.path.insert(0, str(root))
    from cube_app import __version__
    engines = ('htm', 'qtm') if args.profile == 'QtmStrong' else ('htm',)
    builds = {engine:json.loads((root/f'native/{engine}/build/build-info.json').read_text(encoding='utf-8-sig')) for engine in engines}
    for engine, info in builds.items():
        if not info.get('portable') or info['binary_sha256'].lower() != files[f'native/{engine}/build/cube_solver_{engine}.exe']['sha256']:
            raise ValueError(f'{engine} build-info does not match executable')
    sources = application_sources(root, args.profile)
    manifest = {
        "profile": args.profile,
        "app_version": __version__,
        "native_builds": builds,
        "application_source_sha256": {p.relative_to(root).as_posix():metadata(p)["sha256"] for p in sources if p.is_file()},
        "application_source_scope": "Selected profile's application build inputs; excludes development tools and historical engines. Frozen Python inputs need not exist as loose files in the portable installation.",
        "htm_frozen_origin": "ae73ca81af1ed077c059f3345377190bf0ce2882",
        "qtm_frozen_origin": "c01d90dcbc449faf3b6128020e71655a0a47960b" if args.profile == "QtmStrong" else None,
        "files": files,
    }
    args.write.parent.mkdir(parents=True, exist_ok=True)
    args.write.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "profile": args.profile, "files": len(files)}))


if __name__ == "__main__":
    main()
