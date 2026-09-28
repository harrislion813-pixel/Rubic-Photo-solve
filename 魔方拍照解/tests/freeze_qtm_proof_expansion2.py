"""Extend the preselected proof-overlap set with 16 disjoint 18-turn states."""

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
    original = json.loads((ROOT / "tests/qtm_proof_expansion_cases.json").read_text(encoding="utf-8"))
    acceptance = json.loads((ROOT / "tests/qtm_acceptance_public_cases.json").read_text(encoding="utf-8"))
    seen = {case["facelets"] for case in original + acceptance}
    extended = list(original)
    rng = random.Random(2026092805)
    while len(extended) < 40:
        scramble = []
        while len(scramble) < 18:
            move = rng.choice(QUARTERS)
            if scramble and scramble[-1] // 3 == move // 3:
                continue
            scramble.append(move)
        cube = CubieCube()
        for move in scramble:
            cube = cube.apply_move_index(move)
        facelets = to_facelets(cube)
        if facelets in seen:
            continue
        seen.add(facelets)
        tokens = [MOVE_NAMES[move] for move in scramble]
        extended.append({"name": f"expansion-{len(extended):02d}", "facelets": facelets,
                         "incumbent": invert_moves(tokens),
                         "source": {"kind": "fixed_rng_quarter_scramble", "seed": 2026092805,
                                    "scramble_length": 18, "scramble": tokens},
                         "proof": {"method": "timed_native_exhaustive_search_pending"}})
    target = ROOT / "tests/qtm_proof_expansion_extended_cases.json"
    target.write_text(json.dumps(extended, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(extended)} independent proof expansion states: {target}")


if __name__ == "__main__":
    main()
