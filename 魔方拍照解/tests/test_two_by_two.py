from __future__ import annotations

from collections import deque
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX, MOVE_NAMES
from cube_app.two_by_two import (
    TwoByTwoSolver,
    from_facelets_2x2,
    is_solved_2x2,
    rotated_solved_corners,
    to_facelets_2x2,
)


def scrambled(sequence: str) -> CubieCube:
    cube = CubieCube()
    for move in sequence.split():
        cube = cube.apply_move_index(MOVE_INDEX[move])
    return cube


class TwoByTwoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.solver = TwoByTwoSolver()

    def test_compact_facelets_round_trip(self) -> None:
        cube = scrambled("R U2 F' L D B2")
        parsed = from_facelets_2x2(to_facelets_2x2(cube))
        self.assertEqual(parsed.cp, cube.cp)
        self.assertEqual(parsed.co, cube.co)

    def test_all_24_whole_cube_orientations_are_solved(self) -> None:
        self.assertEqual(len(rotated_solved_corners()), 24)
        for cp, co in rotated_solved_corners():
            self.assertTrue(is_solved_2x2(CubieCube(cp=cp, co=co)))

    def test_solution_is_valid_and_known_optimal(self) -> None:
        cube = scrambled("R U R' F2 U' R2 F")
        result = self.solver.solve_cube(cube, timeout_seconds=10)
        self.assertEqual(result.depth, 7)
        self.assertTrue(result.optimal)
        for move in result.moves:
            cube = cube.apply_move_index(MOVE_INDEX[move])
        self.assertTrue(is_solved_2x2(cube))

    def test_shallow_results_match_breadth_first_depths(self) -> None:
        depths = {(CubieCube().cp, CubieCube().co): 0}
        queue = deque([CubieCube()])
        while queue:
            cube = queue.popleft()
            depth = depths[(cube.cp, cube.co)]
            if depth == 3:
                continue
            for name in MOVE_NAMES:
                child = cube.apply_move_index(MOVE_INDEX[name])
                key = (child.cp, child.co)
                if key not in depths:
                    depths[key] = depth + 1
                    queue.append(child)
        for sequence in ("R", "R U", "R U F"):
            cube = scrambled(sequence)
            result = self.solver.solve_cube(cube, timeout_seconds=None)
            self.assertEqual(result.depth, depths[(cube.cp, cube.co)])


if __name__ == "__main__":
    unittest.main()
