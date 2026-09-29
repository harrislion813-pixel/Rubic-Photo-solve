"""Exercise nibble/byte, staged fallback, Unicode paths and repeated native requests."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from benchmark_native import Service


ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / ".cache/qtm-round2/final/cube_solver.exe"
ASSETS = ROOT / ".cache/native"
SIMPLE = {"name": "half-turn", "scramble": "R2", "expected_qtm_depth": 2}
PDB = ["--qtm-pdb", str(ASSETS / "corner_qtm_v3.pdb"),
       "--qtm-phase1-pdb", str(ASSETS / "phase1_qtm_v3.pdb")]


def check_solver(*, strong: Path | None, fallback: Path | None = None,
                 loading: str = "eager", tail: bool = True) -> dict:
    flags = [*PDB, f"--asset-loading={loading}"]
    if strong:
        flags += ["--strong-pdb", str(strong)]
    if fallback:
        flags += ["--strong-pdb-fallback", str(fallback)]
    if tail:
        flags += ["--qtm-tail-pdb", str(ASSETS / "tail_qtm_depth8_v5.pdb")]
    service = Service(BINARY, ["--no-native-candidate"], flags, startup_timeout=30)
    try:
        ready_profile = service.ready["assets"]["QTM"]["profile"]
        if loading == "staged" and (strong or tail):
            expected_stage = "tail" if tail else "strong"
            while True:
                event = service.event(30)
                if event.get("type") == "asset_ready" and event["stage"] == expected_stage:
                    break
        first = service.solve(SIMPLE, 1, 5, "QTM", max_cost=2, incumbent_mode="none")
        second = service.solve(SIMPLE, 4, 5, "QTM", max_cost=2, incumbent_mode="none")
        for run in (first, second):
            if run["result"]["depth"] != 2 or not run["result"]["optimal"]:
                raise AssertionError(run)
        return {"ready_profile": ready_profile, "final_profile": second["result"]["asset_profile"],
                "startup_seconds": service.startup_seconds,
                "first_seconds": first["wall_seconds"], "second_seconds": second["wall_seconds"]}
    finally:
        service.close()


def main() -> None:
    byte = ASSETS / "strong_qtm_v3.pdb"
    nibble = ASSETS / "strong_qtm_v4_nibble.pdb"
    for path in [BINARY, byte, nibble, ASSETS / "tail_qtm_depth8_v5.pdb", *map(Path, PDB[1::2])]:
        if not path.is_file():
            raise FileNotFoundError(path)
    output = {"byte": check_solver(strong=byte), "nibble": check_solver(strong=nibble)}
    with tempfile.TemporaryDirectory(prefix="魔方强表验证-") as directory:
        folder = Path(directory)
        corrupt = folder / "损坏.pdb"
        corrupt.write_bytes(b"not a valid strong PDB")
        output["staged_corrupt_to_byte"] = check_solver(strong=corrupt, fallback=byte,
                                                         loading="staged")
        corrupt_chunk = folder / "损坏数据块.pdb"
        shutil.copyfile(nibble, corrupt_chunk)
        with corrupt_chunk.open("r+b") as stream:
            stream.seek(296 + 10000)
            original = stream.read(1)
            stream.seek(296 + 10000)
            stream.write(bytes([original[0] ^ 1]))
        output["staged_corrupt_chunk_to_byte"] = check_solver(strong=corrupt_chunk, fallback=byte,
                                                               loading="staged")
        output["staged_missing_strong"] = check_solver(strong=folder / "不存在.pdb",
                                                        loading="staged")
        linked = folder / "无损 nibble.pdb"
        os.link(nibble, linked)
        output["unicode_nibble"] = check_solver(strong=linked)
    if (output["byte"]["final_profile"] != "strong" or
            output["nibble"]["final_profile"] != "strong" or
            output["staged_corrupt_to_byte"]["final_profile"] != "strong" or
            output["staged_corrupt_chunk_to_byte"]["final_profile"] != "strong" or
            output["staged_missing_strong"]["final_profile"] != "standard" or
            output["unicode_nibble"]["final_profile"] != "strong"):
        raise AssertionError(output)
    target = ROOT / ".cache/qtm-round2/runtime-matrix.json"
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
