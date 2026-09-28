"""Freeze disjoint QTM acceptance states and independent depth-twelve certificates."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import random

from benchmark_native import legal_state
from cube_app.cubie import CubieCube, MOVE_NAMES, from_facelets, to_facelets
from cube_app.optimal import invert_moves

ROOT = Path(__file__).resolve().parents[1]


QUARTERS = tuple((index, name) for index, name in enumerate(MOVE_NAMES) if not name.endswith("2"))


def ball(start: CubieCube, radius: int) -> dict[CubieCube, int]:
    """Independent unrestricted BFS; consecutive same-face turns are retained."""
    distances = {start: 0}
    frontier = deque([start])
    while frontier:
        cube = frontier.popleft()
        depth = distances[cube]
        if depth == radius:
            continue
        for move, _ in QUARTERS:
            child = cube.apply_move_index(move)
            if child not in distances:
                distances[child] = depth + 1
                frontier.append(child)
    return distances


def main() -> None:
    reference = ball(CubieCube(), 6)
    cases: list[dict] = []
    seen: set[str] = set()
    rng = random.Random(2026092801)
    while len(cases) < 12:
        sequence = []
        while len(sequence) < 12:
            candidate = rng.choice(QUARTERS)
            if sequence and candidate[0] // 3 == sequence[-1][0] // 3:
                continue
            sequence.append(candidate)
        cube = CubieCube()
        for move, _ in sequence:
            cube = cube.apply_move_index(move)
        facelets = to_facelets(cube)
        if facelets in seen:
            continue
        target = ball(cube, 6)
        distance = min((a + reference[state] for state, a in target.items() if state in reference), default=13)
        if distance != 12:
            continue
        seen.add(facelets)
        scramble = [name for _, name in sequence]
        cases.append({
            "name": f"oracle12-{len(cases):02d}",
            "facelets": facelets,
            "incumbent": invert_moves(scramble),
            "expected_qtm_depth": 12,
            "source": {"kind": "fixed_rng_quarter_scramble", "seed": 2026092801, "scramble": scramble},
            "proof": {"method": "bidirectional_unrestricted_qtm_bfs", "radius_each_side": 6,
                      "goal_ball_states": len(reference), "minimum_meeting_cost": distance},
        })

    for offset in range(32):
        seed = 20271000 + offset
        cube = legal_state(seed)
        facelets = to_facelets(cube)
        assert from_facelets(facelets) == cube
        cases.append({"name": f"legal-{seed}", "facelets": facelets,
                      "source": {"kind": "independent_legal_state_rng", "seed": seed}})

    superflip = CubieCube(eo=(1,) * 12)
    cases.append({"name": "superflip", "facelets": to_facelets(superflip),
                  "source": {"kind": "independently_constructed_cubie_state", "description": "all 12 edges flipped"}})
    pressure_rng = random.Random(2026092803)
    for index in range(3):
        sequence = [pressure_rng.choice(QUARTERS) for _ in range(25)]
        cube = CubieCube()
        for move, _ in sequence:
            cube = cube.apply_move_index(move)
        facelets = to_facelets(cube)
        assert from_facelets(facelets) == cube
        scramble = [name for _, name in sequence]
        cases.append({"name": f"pressure-{index:02d}", "facelets": facelets,
                      "incumbent": invert_moves(scramble),
                      "source": {"kind": "fixed_rng_quarter_scramble", "seed": 2026092803,
                                 "scramble": scramble}})

    assert len(cases) == 48 and len({case["facelets"] for case in cases}) == 48
    target = ROOT / "tests" / "qtm_acceptance_cases.json"
    target.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases, goal BFS radius 6 = {len(reference)} states: {target}")


if __name__ == "__main__":
    main()
