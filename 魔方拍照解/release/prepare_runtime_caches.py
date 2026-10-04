"""Generate every small runtime cache locally, keeping HTM and QTM separate."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("HtmFull", "QtmStrong"), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from cube_app.solvers.htm.tables import load_or_build_tables as prepare_htm
    from cube_app.solvers.htm.two_by_two_tables import load_or_build as prepare_htm_2x2

    htm_cache = root / ".cache" / "htm"
    prepare_htm(str(htm_cache))
    prepare_htm_2x2(str(htm_cache))
    paths = [htm_cache / "solver_tables_v3.pkl"]
    engines = ["htm"]
    if args.profile == "QtmStrong":
        from cube_app.solvers.qtm.tables import load_or_build_tables as prepare_qtm
        from cube_app.solvers.qtm.two_by_two_tables import load_or_build as prepare_qtm_2x2
        from cube_app.solvers.qtm.qtm_small import (
            build_qtm_small_tables, load_qtm_small_tables, save_qtm_small_tables,
        )

        qtm_cache = root / ".cache" / "qtm"
        qtm_tables = prepare_qtm(str(qtm_cache))
        prepare_qtm_2x2(str(qtm_cache), metric="QTM")
        if load_qtm_small_tables(qtm_cache) is None:
            print("Building QTM fallback pruning tables; keep this window open.", flush=True)
            save_qtm_small_tables(build_qtm_small_tables(qtm_tables), qtm_cache)
        paths.append(qtm_cache / "solver_tables_v3.pkl")
        engines.append("qtm")
    for engine in engines:
        executable = root / "native" / engine / "build" / f"cube_solver_{engine}.exe"
        if not executable.is_file():
            raise FileNotFoundError(f"Compile native/{engine}/build.ps1 first: {executable}")
        cache_name = "coordinates_htm_v1.bin" if engine == "htm" else "coordinates_dual_v2.bin"
        environment = {key: value for key, value in os.environ.items() if not key.startswith("CUBE_")}
        environment["CUBE_NATIVE_COORDINATE_CACHE"] = str(root / ".cache" / engine / cache_name)
        subprocess.run([str(executable), "check-heuristic", "--depth", "0"],
                       cwd=root, env=environment, check=True)
        if engine == "htm":
            # This cache has its own HTM convention version and integrity check.
            environment["CUBE_HTM_SYMMETRY_CACHE"] = str(root / ".cache/htm/phase1_symmetry_htm_v1.bin")
            subprocess.run([str(executable), "symmetry-info"], cwd=root, env=environment, check=True)
            subprocess.run([str(executable), "candidate", "U" * 9 + "R" * 9 + "F" * 9 + "D" * 9 + "L" * 9 + "B" * 9,
                            "--timeout", "0.001"], cwd=root, env=environment, check=True)
    first = [digest(path) for path in paths]
    prepare_htm(str(htm_cache))
    if args.profile == "QtmStrong":
        prepare_qtm(str(qtm_cache))
    if first != [digest(path) for path in paths]:
        raise RuntimeError("runtime fallback cache changed on a second load")
    print("Prepared stable Python fallback caches:", *(path.relative_to(root).as_posix() for path in paths))


if __name__ == "__main__":
    main()
