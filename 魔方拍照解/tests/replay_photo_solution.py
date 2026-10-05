"""Independently verify formulas returned by the actual photo/browser flow."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cube_app.cubie import MOVE_INDEX, from_facelets  # noqa: E402
from cube_app.metrics import solution_cost  # noqa: E402
from cube_app.solvers.htm.two_by_two import from_facelets_2x2, is_solved_2x2  # noqa: E402


def main() -> None:
    payload = json.load(sys.stdin)
    size = payload["cube_size"]
    assert size in (2, 3)
    initial = (from_facelets_2x2 if size == 2 else from_facelets)(payload["facelets"])
    assert payload["formulas"], "no candidate formula returned"
    for formula in payload["formulas"]:
        state = initial
        for move in formula["moves"]:
            state = state.apply_move_index(MOVE_INDEX[move])
        assert is_solved_2x2(state) if size == 2 else state.is_solved(), "candidate does not restore the cube"
        assert formula.get("metric", "HTM") == "HTM", "photo gate requested HTM"
        assert solution_cost(formula["moves"], "HTM") == formula.get("depth", formula.get("cost"))
    print(json.dumps({"replayed_formulas": len(payload["formulas"]), "cube_size": size}))


if __name__ == "__main__":
    main()
