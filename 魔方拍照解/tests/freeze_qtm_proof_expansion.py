"""Freeze an unbiased extra set for timed QTM proof overlap analysis."""

from __future__ import annotations

import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_NAMES, to_facelets  # noqa: E402
from cube_app.optimal import invert_moves  # noqa: E402

QUARTERS = tuple(index for index, name in enumerate(MOVE_NAMES) if not name.endswith("2"))


def main() -> None:
    rng = random.Random(2026092804)
    acceptance = json.loads((ROOT / "tests/qtm_acceptance_cases.json").read_text(encoding="utf-8"))
    seen = {case["facelets"] for case in acceptance}
    cases = []
    for depth in (15, 16, 17):
        while sum(case["source"]["scramble_length"] == depth for case in cases) < 8:
            sequence = []
            while len(sequence) < depth:
                move = rng.choice(QUARTERS)
                if sequence and move // 3 == sequence[-1] // 3:
                    continue
                sequence.append(move)
            cube = CubieCube()
            for move in sequence:
                cube = cube.apply_move_index(move)
            facelets = to_facelets(cube)
            if facelets in seen:
                continue
            seen.add(facelets)
            scramble = [MOVE_NAMES[move] for move in sequence]
            cases.append({"name": f"expansion-{len(cases):02d}", "facelets": facelets,
                          "incumbent": invert_moves(scramble),
                          "source": {"kind": "fixed_rng_quarter_scramble", "seed": 2026092804,
                                     "scramble_length": depth, "scramble": scramble},
                          "proof": {"method": "timed_native_exhaustive_search_pending"}})
    target = ROOT / "tests/qtm_proof_expansion_cases.json"
    target.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} QTM proof expansion states: {target}")


if __name__ == "__main__":
    main()
