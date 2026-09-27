from __future__ import annotations

import json
import os
import random
import subprocess
import tempfile
import threading
import unittest

import pytest

from cube_app.coords import get_corner_perm, get_flip, get_slice_comb, get_twist
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.optimal import invert_moves
from cube_app.native import NATIVE_EXE, native_solver_available
from cube_app.native import solve_native
from cube_app.native import NativeSolverCancelled, NativeSolverTimeout, _PERSISTENT_SOLVER


def require_or_skip(condition: bool, *, environment_variable: str, reason: str):
    if not condition and os.environ.get(environment_variable, "").strip().lower() in {"1", "true", "yes"}:
        raise RuntimeError(f"{reason}; {environment_variable} requires this CI job to provide it")
    return unittest.skipUnless(condition, reason)


class NativeCommandMixin:
    def run_native(self, *arguments: str) -> dict:
        output = subprocess.check_output(
            [str(NATIVE_EXE), *arguments],
            text=True,
            encoding="utf-8",
        )
        return json.loads(output)


@pytest.mark.native_binary
@require_or_skip(
    NATIVE_EXE.is_file(),
    environment_variable="REQUIRE_NATIVE_BINARY",
    reason="原生求解器尚未编译",
)
class NativeBinaryTests(NativeCommandMixin, unittest.TestCase):
    def test_coordinate_cache_corruption_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "coordinates.bin")
            environment = {**os.environ, "CUBE_NATIVE_COORDINATE_CACHE": path}

            def check():
                return json.loads(
                    subprocess.check_output(
                        [str(NATIVE_EXE), "check-heuristic", "--depth", "1"],
                        text=True,
                        encoding="utf-8",
                        env=environment,
                    )
                )

            self.assertTrue(check()["ok"])
            with open(path, "rb") as stream:
                original = stream.read()
            with open(path, "wb") as stream:
                stream.write(b"corrupt")
            self.assertTrue(check()["ok"])
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), original)

    def test_heuristic_and_staged_coordinates_match_shallow_bfs_without_pdb(self):
        result = self.run_native("check-heuristic", "--depth", "3")
        self.assertEqual(result["checked"], 3502)
        self.assertGreater(result["small_pdb_queries"], 0)

    def test_coordinates_match_python_for_random_states(self) -> None:
        generator = random.Random(42)
        for _ in range(30):
            cube = CubieCube()
            for _ in range(generator.randrange(1, 35)):
                cube = cube.apply_move_index(generator.randrange(18))
            result = self.run_native("validate", to_facelets(cube))
            self.assertEqual(result["facelets"], to_facelets(cube))
            self.assertEqual(result["twist"], get_twist(cube))
            self.assertEqual(result["flip"], get_flip(cube))
            self.assertEqual(result["corner_perm"], get_corner_perm(cube))
            self.assertEqual(result["slice_comb"], get_slice_comb(cube))

    def test_native_inverse_round_trip(self) -> None:
        cube = CubieCube()
        for move in "R U F2 L D B' R2 U'".split():
            cube = cube.apply_move_index(MOVE_INDEX[move])
        first = self.run_native("validate", to_facelets(cube))
        second = self.run_native("validate", first["inverse_facelets"])
        self.assertEqual(second["inverse_facelets"], to_facelets(cube))

    def test_phase1_symmetry_has_expected_class_count(self) -> None:
        result = self.run_native("symmetry-info")
        self.assertEqual(result["symmetries"], 16)
        self.assertEqual(result["flip_slice_classes"], 64_430)


@pytest.mark.native_pdb
@require_or_skip(
    native_solver_available(),
    environment_variable="REQUIRE_NATIVE_PDB",
    reason="原生求解器或必需的模式数据库尚未构建",
)
class NativePdbSolverTests(NativeCommandMixin, unittest.TestCase):
    def test_new_incumbent_is_accepted_during_search(self):
        scramble = "U' F L R' D' B' F U' B2 L D R2 B2 L2 U2 L' U2 R'".split()
        cube = CubieCube()
        for name in scramble:
            cube = cube.apply_move_index(MOVE_INDEX[name])
        improved = invert_moves(scramble)
        cancel = threading.Event()
        events = []

        def progress(event):
            events.append(event)
            if event["upper_bound"] == 17:
                cancel.set()

        with self.assertRaises(NativeSolverCancelled):
            solve_native(
                cube,
                max_depth=20,
                timeout_seconds=15,
                incumbent_moves=[*improved, "U", "U'"],
                incumbent_provider=lambda: improved,
                cancel_event=cancel,
                threads=4,
                progress_callback=progress,
            )
        self.assertTrue(any(event["upper_bound"] == 17 for event in events))
        self.assertTrue(any(event["generated_candidates"] > 0 for event in events))

    def test_complete_pdb_heuristic_matches_bfs_without_small_queries(self):
        result = self.run_native(
            "check-heuristic",
            "--depth",
            "4",
            "--pdb",
            ".cache/native/corner_htm_v2.pdb",
            "--phase1-pdb",
            ".cache/native/phase1_sym_htm_v2.pdb",
        )
        self.assertEqual(result["checked"], 46741)
        self.assertEqual(result["small_pdb_queries"], 0)

    def test_partial_pdb_keeps_small_table_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "partial.pdb")
            self.run_native("build-corner-pdb", path, "--coverage-depth", "0", "--threads", "2")
            phase1 = os.path.join(directory, "partial-phase1.pdb")
            self.run_native("build-phase1-pdb", phase1, "--coverage-depth", "0", "--threads", "2")
            result = self.run_native("check-heuristic", "--depth", "3", "--pdb", path, "--phase1-pdb", phase1)
            self.assertEqual(result["checked"], 3502)
            self.assertGreater(result["small_pdb_queries"], 0)

    def test_unlimited_inverse_search_and_thread_counts(self):
        cube = CubieCube().apply_move_index(MOVE_INDEX["R"]).apply_move_index(MOVE_INDEX["U"])
        for threads in (1, 2, 4):
            result = self.run_native(
                "solve",
                to_facelets(cube),
                "--timeout",
                "0",
                "--threads",
                str(threads),
                "--inverse-direction",
                "--pdb",
                ".cache/native/corner_htm_v2.pdb",
                "--phase1-pdb",
                ".cache/native/phase1_sym_htm_v2.pdb",
            )
            self.assertEqual(result["depth"], 2)
            self.assertTrue(result["optimal"])
            verified = cube
            for move in result["moves"]:
                verified = verified.apply_move_index(MOVE_INDEX[move])
            self.assertTrue(verified.is_solved())

    def test_cancel_keeps_process_and_resumes_completed_depth(self):
        cube = CubieCube()
        for move in "U' F L R' D' B' F U' B2 L D R2 B2 L2 U2 L' U2 R'".split():
            cube = cube.apply_move_index(MOVE_INDEX[move])
        cancel = threading.Event()
        events = []

        def progress(event):
            events.append(event)
            if event["completed_depth"] >= 15:
                cancel.set()

        with self.assertRaises(NativeSolverCancelled):
            solve_native(
                cube,
                max_depth=20,
                timeout_seconds=30,
                incumbent_moves=None,
                cancel_event=cancel,
                threads=2,
                progress_callback=progress,
            )
        process = _PERSISTENT_SOLVER._process
        self.assertIsNotNone(process)
        resumed = []
        with self.assertRaises(NativeSolverTimeout):
            solve_native(
                cube,
                max_depth=20,
                timeout_seconds=0.15,
                incumbent_moves=None,
                cancel_event=None,
                threads=2,
                progress_callback=resumed.append,
            )
        self.assertIs(_PERSISTENT_SOLVER._process, process)
        self.assertGreaterEqual(resumed[0]["completed_depth"], 15)
        self.assertEqual(resumed[0]["current_depth"], resumed[0]["completed_depth"] + 1)
        self.assertLess(resumed[-1]["completed_depth"], resumed[-1]["current_depth"])
        result = solve_native(CubieCube(), max_depth=0, timeout_seconds=None, incumbent_moves=None, cancel_event=None)
        self.assertEqual(result["depth"], 0)

    def test_known_short_depth_is_proved_optimal(self) -> None:
        cube = CubieCube()
        for move in "R U F2 L D".split():
            cube = cube.apply_move_index(MOVE_INDEX[move])
        result = self.run_native(
            "solve",
            to_facelets(cube),
            "--timeout",
            "5",
            "--threads",
            "4",
            "--pdb",
            ".cache/native/corner_htm_v2.pdb",
            "--phase1-pdb",
            ".cache/native/phase1_sym_htm_v2.pdb",
        )
        self.assertEqual(result["depth"], 5)
        self.assertTrue(result["optimal"])
        for move in result["moves"]:
            cube = cube.apply_move_index(MOVE_INDEX[move])
        self.assertTrue(cube.is_solved())

    def test_python_bridge_streams_structured_progress(self) -> None:
        cube = CubieCube()
        for move in "R U F2 L D".split():
            cube = cube.apply_move_index(MOVE_INDEX[move])
        events = []
        result = solve_native(
            cube,
            max_depth=5,
            timeout_seconds=5,
            incumbent_moves=None,
            cancel_event=None,
            threads=2,
            progress_callback=events.append,
        )
        self.assertIsNotNone(result)
        self.assertTrue(events)
        self.assertTrue(all(event.get("type") == "progress" for event in events))
        self.assertEqual(events[-1]["current_depth"], 5)
        self.assertTrue(events[-1]["found"])


if __name__ == "__main__":
    unittest.main()
