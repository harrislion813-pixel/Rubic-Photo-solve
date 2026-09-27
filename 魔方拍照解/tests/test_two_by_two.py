from __future__ import annotations

from collections import deque
from pathlib import Path
import sys
import unittest
import random
import tempfile
import threading
import time
from unittest.mock import patch

import numpy as np

from cube_app.two_by_two_tables import CACHE_NAMES, DIAMETERS, ENTRIES, _load, load_or_build
from cube_app.metrics import solution_cost
from cube_app.coords import rank_to_perm


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
    def test_random_states_in_all_user_orientations_keep_correct_move_mapping(self):
        generator = random.Random(20260927)
        for _ in range(12):
            cube = scrambled(" ".join(generator.choice(MOVE_NAMES) for _ in range(20)))
            for metric in ("HTM", "QTM"):
                distance = self.solver.solve_cube(cube, metric=metric).depth
                for cp, co in rotated_solved_corners():
                    rotated = cube.moved(CubieCube(cp=cp, co=co))
                    result = self.solver.solve_cube(rotated, metric=metric)
                    self.assertEqual(result.depth, distance)
                    self.assertEqual(result.metric, metric)
                    self.assertEqual(solution_cost(result.moves, metric), distance)
                    for name in result.moves:
                        rotated = rotated.apply_move_index(MOVE_INDEX[name])
                    self.assertTrue(is_solved_2x2(rotated))

    def test_full_table_cache_is_versioned_and_corruption_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as directory:
            for metric in ("HTM", "QTM"):
                tables = load_or_build(directory, metric=metric)
                self.assertEqual(len(tables[0]), ENTRIES)
                self.assertEqual(int(tables[0].max()), DIAMETERS[metric])
                self.assertEqual(np.count_nonzero(tables[0] == 255), 0)
                cache = Path(directory) / CACHE_NAMES[metric]
                raw = bytearray(cache.read_bytes())
                raw[100] ^= 1
                cache.write_bytes(raw)
                rebuilt = load_or_build(directory, metric=metric)
                self.assertEqual(rebuilt[0].tobytes(), tables[0].tobytes())
            with self.assertRaises(ValueError):
                _load(Path(directory) / CACHE_NAMES["HTM"], "QTM")

    def test_mode_cache_budget_and_half_turn_cost(self):
        cube = scrambled("R2")
        self.assertEqual(self.solver.solve_cube(cube).depth, 1)
        with self.assertRaisesRegex(ValueError, "预算.*不足"):
            self.solver.solve_cube(cube, max_depth=1, metric="QTM")
        half_turn = self.solver.solve_cube(cube, max_depth=2, metric="QTM")
        self.assertEqual(half_turn.depth, 2)
        self.assertEqual(half_turn.moves, ["R2"])
        self.assertEqual(self.solver.solve_cube(cube, metric="htm").depth, 1)
        self.assertEqual(set(self.solver._tables), {"HTM", "QTM"})
        for metric in ("HTM", "QTM"):
            zero = self.solver.solve_cube(CubieCube(), max_depth=0, metric=metric)
            self.assertEqual((zero.metric, zero.depth), (metric, 0))
        with self.assertRaises(ValueError):
            self.solver.solve_cube(cube, metric="other")
        with self.assertRaises(ValueError):
            self.solver.solve_cube(cube, max_depth=1.5)

    def test_read_only_cache_and_initialization_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, "write_bytes", side_effect=OSError("read-only")):
                tables = load_or_build(directory, metric="QTM")
            self.assertEqual(int(tables[0].max()), 14)
            self.assertFalse(tables[0].flags.writeable)
            with self.assertRaises(TimeoutError):
                load_or_build(directory, deadline=0, metric="QTM")

    def test_qtm_default_covers_diameter_14_and_generic_budget_is_clamped(self):
        from cube_app.two_by_two_tables import POSITIONS, TWISTS
        distance, _, _ = load_or_build(str(self.solver.cache_dir), metric="QTM")
        index = int(np.flatnonzero(distance == 14)[0])
        perm, twist = divmod(index, TWISTS)
        cp, co = list(range(8)), [0] * 8
        for position, label in zip(POSITIONS, rank_to_perm(perm, 7)):
            cp[position] = POSITIONS[label]
        for position in reversed(POSITIONS[:-1]):
            co[position] = twist % 3
            twist //= 3
        co[7] = -sum(co) % 3
        cube = CubieCube(cp=tuple(cp), co=tuple(co))
        result = self.solver.solve_cube(cube, metric="QTM")
        self.assertEqual((result.depth, solution_cost(result.moves, "QTM")), (14, 14))
        self.assertEqual(self.solver.solve_cube(cube, max_depth=26, metric="QTM").depth, 14)
        with self.assertRaisesRegex(ValueError, "预算.*不足"):
            self.solver.solve_cube(cube, max_depth=13, metric="QTM")

    def test_deadline_includes_wait_for_other_table_builder(self):
        from cube_app.two_by_two_tables import _LOCK
        locked, release = threading.Event(), threading.Event()
        def hold_lock():
            with _LOCK:
                locked.set()
                release.wait(2)
        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(locked.wait(1))
        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                load_or_build(str(self.solver.cache_dir), deadline=started + 0.02, metric="QTM")
            self.assertLess(time.monotonic() - started, 1)
        finally:
            release.set()
            holder.join()

    def test_qtm_reoptimizes_instead_of_repricing_htm_formula(self):
        # Independent meet-in-the-middle BFS uses physical corner moves only;
        # it never queries production distances, normalization, or search.
        cube = from_facelets_2x2("LLURUFDDRBDRLFDBBFLFUURB")
        htm_formula = "F2 U' R2 U' F R U2".split()
        self.assertEqual(self._independent_distance(cube, MOVE_NAMES[:9], 4), 7)
        quarter_moves = tuple(name for name in MOVE_NAMES[:9] if not name.endswith("2"))
        self.assertEqual(self._independent_distance(cube, quarter_moves, 4), 8)
        self.assertEqual(solution_cost(htm_formula, "QTM"), 10)
        verified = cube
        for name in htm_formula:
            verified = verified.apply_move_index(MOVE_INDEX[name])
        self.assertTrue(is_solved_2x2(verified))
        htm = self.solver.solve_cube(cube, metric="HTM")
        qtm = self.solver.solve_cube(cube, metric="QTM")
        self.assertEqual((htm.depth, qtm.depth), (7, 8))
        self.assertEqual(solution_cost(qtm.moves, "QTM"), 8)

    @staticmethod
    def _independent_distance(cube, moves, radius):
        def ball(start):
            seen = {(start.cp, start.co): 0}
            queue = deque([start])
            while queue:
                current = queue.popleft()
                depth = seen[(current.cp, current.co)]
                if depth == radius:
                    continue
                for name in moves:
                    child = current.apply_move_index(MOVE_INDEX[name])
                    key = (child.cp, child.co)
                    if key not in seen:
                        seen[key] = depth + 1
                        queue.append(child)
            return seen
        left, right = ball(CubieCube()), ball(cube)
        return min(left[key] + right[key] for key in left.keys() & right.keys())

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
