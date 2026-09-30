"""Replay the H0 result recorded before strict validation was added to the runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import MOVE_INDEX, from_facelets  # noqa: E402
from cube_app.metrics import solution_cost  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    source = json.loads(raw)
    output = {"input": str(args.input.resolve()), "input_sha256": hashlib.sha256(raw).hexdigest(),
              "runs": []}
    for run in source["runs"]:
        payload = run["final"].get("result") or run["final"]
        state = from_facelets(run["submitted_facelets"])
        for move in payload["moves"]:
            state = state.apply_move_index(MOVE_INDEX[move])
        cost = solution_cost(payload["moves"], "HTM")
        accepted = (state.is_solved() and payload.get("optimal") is True
                    and run["final"].get("status", run["final"].get("proof_status")) == "complete"
                    and cost == payload.get("depth"))
        output["runs"].append({"name": run["name"], "cost": cost, "strict_proof_verified": accepted})
        if not accepted:
            raise AssertionError(f"H0 result failed replay: {run['name']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("H0 verified real states:", len(output["runs"]))


if __name__ == "__main__":
    main()
