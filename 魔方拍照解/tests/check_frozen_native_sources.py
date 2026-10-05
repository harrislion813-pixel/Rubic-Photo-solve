"""Record which native source files are byte-identical to H0 and Q0."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def compare(reference: Path, migrated: Path) -> dict:
    result = {}
    for folder in ("src", "include"):
        for current in sorted((migrated / folder).rglob("*")):
            if not current.is_file():
                continue
            relative = current.relative_to(migrated)
            original = reference / relative
            result[str(relative).replace("\\", "/")] = {
                "source_sha256": sha256(original) if original.exists() else None,
                "isolated_sha256": sha256(current),
                "identical_bytes": original.exists() and current.read_bytes() == original.read_bytes(),
                "identical": original.exists() and normalized(current) == normalized(original),
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--q0", type=Path, required=True)
    parser.add_argument("--h0", type=Path, required=True, help="Explicit historical H0 checkout or extracted source archive")
    parser.add_argument("--h1", type=Path, help="Historical H1 native tree; defaults to the current HTM tree")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = {
        "H0_to_H1": compare(args.h0.resolve() / "native", args.h1.resolve() if args.h1 else root / "native" / "htm"),
        "Q0_to_Q1": compare(args.q0.resolve() / "native", root / "native" / "qtm"),
    }
    if not all(item["identical"] for item in output["H0_to_H1"].values()):
        raise RuntimeError("HTM native source differs from the H0 frozen source")
    qtm_differences = [name for name, item in output["Q0_to_Q1"].items() if not item["identical"]]
    if qtm_differences != ["src/main.cpp"]:
        raise RuntimeError(f"unexpected QTM native source changes: {qtm_differences}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HTM identical: {len(output['H0_to_H1'])}; QTM changed: {qtm_differences}")


if __name__ == "__main__":
    main()
