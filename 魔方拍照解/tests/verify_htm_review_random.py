"""Frozen independent shallow random states through the final default HTTP path."""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cube_app.cubie import CubieCube, MOVE_NAMES, to_facelets  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error("refusing to overwrite evidence")
    folder = args.output.parent / args.output.stem
    folder.mkdir(parents=True, exist_ok=False)
    generator = random.Random(20261005)
    cases = []
    for depth in range(5, 13):
        state = CubieCube()
        moves = []
        last_face = -1
        for _ in range(depth):
            allowed = [m for m in range(18) if m // 3 != last_face]
            move = generator.choice(allowed)
            state = state.apply_move_index(move)
            moves.append(MOVE_NAMES[move])
            last_face = move // 3
        cases.append({"name": f"random-{depth}", "facelets": to_facelets(state), "generation_moves": moves})
    # Freeze all inputs before any solver is invoked. Generation moves are never sent.
    report = {"seed": 20261005, "scope": "Independent shallow random states; correctness and default routing, not hard-case completion claims",
              "cases": cases, "runs": []}
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    environment = {k: v for k, v in os.environ.items() if not k.startswith("CUBE_")}
    for case in cases:
        output = folder / (case["name"] + ".json")
        completed = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tests/htm_http_request_probe.py"),
            "--root", str(ROOT), "--facelets", case["facelets"], "--output", str(output)], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert completed.returncode == 0, completed.stderr
        row = json.loads(output.read_text(encoding="utf-8"))
        assert row["terminal"]["status"] == "complete" and row["terminal"]["result"]["optimal"]
        assert row["native_candidate_policy"] == "six"
        assert row["terminal"]["result"]["depth"] <= len(case["generation_moves"])
        report["runs"].append({"name": case["name"], **row})
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"name": case["name"], "seconds": row["wall_seconds"], "depth": row["terminal"]["result"]["depth"]}), flush=True)


if __name__ == "__main__":
    main()
