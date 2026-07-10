from __future__ import annotations

import unittest
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cube_app.optimal as optimal
from cube_app.cubie import CubieCube, MOVE_INDEX
from cube_app.fast import FastTwoPhaseSolver


def scrambled(sequence: str) -> CubieCube:
    cube = CubieCube()
    for move in sequence.split():
        cube = cube.apply_move_index(MOVE_INDEX[move])
    return cube


def apply_solution(cube: CubieCube, moves: list[str]) -> CubieCube:
    for move in moves:
        cube = cube.apply_move_index(MOVE_INDEX[move])
    return cube


class OptimalSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.solver = optimal.OptimalSolver(ROOT / ".cache")

    def test_known_short_optimal_depths(self) -> None:
        cases = {
            "R": 1,
            "R U": 2,
            "R U F2 L D": 5,
            "R U R' U' F2 D": 6,
        }
        for sequence, expected_depth in cases.items():
            with self.subTest(sequence=sequence):
                cube = scrambled(sequence)
                result = self.solver.solve_cube(cube, timeout_seconds=5)
                self.assertEqual(result.depth, expected_depth)
                self.assertTrue(result.optimal)
                self.assertTrue(apply_solution(cube, result.moves).is_solved())

    def test_parallel_root_search_smoke(self) -> None:
        previous_threshold = optimal._PARALLEL_MIN_DEPTH
        optimal._PARALLEL_MIN_DEPTH = 1
        try:
            cube = scrambled("R U F2")
            solver = optimal.OptimalSolver(ROOT / ".cache", parallel=True, max_workers=2)
            result = solver.solve_cube(cube, timeout_seconds=10)
        finally:
            optimal._PARALLEL_MIN_DEPTH = previous_threshold
        self.assertEqual(result.depth, 3)
        self.assertTrue(apply_solution(cube, result.moves).is_solved())

    def test_incumbent_is_returned_when_no_shorter_solution_exists(self) -> None:
        cube = scrambled("R")
        result = self.solver.solve_cube(
            cube,
            timeout_seconds=5,
            upper_bound=1,
            incumbent_moves=["R'"],
        )
        self.assertEqual(result.moves, ["R'"])
        self.assertEqual(result.depth, 1)
        self.assertTrue(result.optimal)

    def test_pre_cancelled_search_stops_before_work_begins(self) -> None:
        cancel_event = threading.Event()
        cancel_event.set()
        with self.assertRaises(optimal.SearchCancelled):
            self.solver.solve_cube(scrambled("R"), timeout_seconds=5, cancel_event=cancel_event)


class FastTwoPhaseSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.solver = FastTwoPhaseSolver(ROOT / ".cache")
        _ = cls.solver.tables

    def test_returns_valid_non_optimal_solution_for_deep_state(self) -> None:
        cube = scrambled("B' U' L' U2 F L' F2 U2 R' U L D2 F2 D' L D'")
        result = self.solver.solve_cube(cube, timeout_seconds=5)
        self.assertFalse(result.optimal)
        self.assertLessEqual(result.depth, 26)
        self.assertTrue(apply_solution(cube, result.moves).is_solved())

    def test_solved_cube_is_known_optimal(self) -> None:
        result = self.solver.solve_cube(CubieCube(), timeout_seconds=1)
        self.assertTrue(result.optimal)
        self.assertEqual(result.depth, 0)


if __name__ == "__main__":
    unittest.main()
