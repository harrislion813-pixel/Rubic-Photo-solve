from __future__ import annotations

import json
import os
import random
import subprocess
import unittest

import pytest

from cube_app.coords import get_corner_perm, get_flip, get_slice_comb, get_twist
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.native import NATIVE_EXE, native_solver_available
from cube_app.native import solve_native


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
