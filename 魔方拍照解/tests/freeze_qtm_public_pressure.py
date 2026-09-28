"""Freeze published QTM distance-25/26 positions without changing existing runs."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets  # noqa: E402
from cube_app.optimal import invert_moves  # noqa: E402


SOURCE = "https://www.cube20.org/distance20s/"
PUBLISHED = (
    ("superflip-fourspot", 26, "U1U1F1U1U1R3L1F1F1U1F3B3R1L1U1U1R1U1D3R1L3D1R3L3D1D1"),
    ("antipode-neighbor-a", 25, "U1U1F1U1U1R3L1F1F1U1F3B3R1L1U1U1R1U1D3R1L3D1R3L3D3"),
    ("antipode-neighbor-b", 25, "U1F1U1U1R3L1F1F1U1F3B3R1L1U1U1L1U1D3R3L1D1R3L3U1U1"),
)


def decode_quarter_scramble(compact: str) -> list[str]:
    if len(compact) % 2:
        raise ValueError("published quarter-turn string has odd length")
    moves = []
    for offset in range(0, len(compact), 2):
        face, amount = compact[offset:offset + 2]
        if face not in "URFDLB" or amount not in "13":
            raise ValueError("invalid published quarter-turn token")
        moves.append(face + ("'" if amount == "3" else ""))
    return moves


def main() -> None:
    cases = []
    for name, depth, compact in PUBLISHED:
        scramble = decode_quarter_scramble(compact)
        if len(scramble) != depth:
            raise AssertionError(f"published depth and scramble length differ for {name}")
        cube = CubieCube()
        for move in scramble:
            cube = cube.apply_move_index(MOVE_INDEX[move])
        if depth == 26 and (not cube.moved(cube).is_solved() or cube.eo != (1,) * 12):
            raise AssertionError("published antipode is not the self-inverse all-edge-flip position")
        incumbent = invert_moves(scramble)
        restored = cube
        for move in incumbent:
            restored = restored.apply_move_index(MOVE_INDEX[move])
        if not restored.is_solved():
            raise AssertionError(f"published scramble does not invert for {name}")
        cases.append({"name": name, "facelets": to_facelets(cube),
                      "incumbent": incumbent, "expected_qtm_depth": depth,
                      "source": {"kind": "published_qtm_antipode", "url": SOURCE,
                                 "compact_quarter_scramble": compact, "scramble": scramble},
                      "proof": {"method": "published_exhaustive_QTM_distance",
                                "source": SOURCE, "depth": depth}})
    if len({case["facelets"] for case in cases}) != len(cases):
        raise AssertionError("published pressure states are not distinct")
    original = json.loads((ROOT / "tests/qtm_acceptance_cases.json").read_text(encoding="utf-8"))
    retained = [case for case in original if case["name"].startswith(("oracle12-", "legal-")) or
                case["name"] == "superflip"]
    if len(retained) != 45:
        raise AssertionError("expected 12 oracles, 32 random states, and superflip")
    combined = retained + cases
    for path, payload in ((ROOT / "tests/qtm_public_pressure_cases.json", cases),
                          (ROOT / "tests/qtm_acceptance_public_cases.json", combined)):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(payload)} cases: {path}")


if __name__ == "__main__":
    main()
