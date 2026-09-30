"""Build each engine's Python fallback caches with its packaged module paths."""

from __future__ import annotations

import argparse
import hashlib
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

    htm_cache = root / ".cache" / "htm"
    prepare_htm(str(htm_cache))
    paths = [htm_cache / "solver_tables_v3.pkl"]
    if args.profile == "QtmStrong":
        from cube_app.solvers.qtm.tables import load_or_build_tables as prepare_qtm

        qtm_cache = root / ".cache" / "qtm"
        prepare_qtm(str(qtm_cache))
        paths.append(qtm_cache / "solver_tables_v3.pkl")
    first = [digest(path) for path in paths]
    prepare_htm(str(htm_cache))
    if args.profile == "QtmStrong":
        prepare_qtm(str(qtm_cache))
    if first != [digest(path) for path in paths]:
        raise RuntimeError("runtime fallback cache changed on a second load")
    print("Prepared stable Python fallback caches:", *(str(path) for path in paths))


if __name__ == "__main__":
    main()
