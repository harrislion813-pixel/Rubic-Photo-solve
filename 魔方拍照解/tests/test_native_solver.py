from __future__ import annotations

import json
import io
import os
import random
import subprocess
import tempfile
import threading
import unittest
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from cube_app.coords import get_corner_perm, get_flip, get_slice_comb, get_twist
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.optimal import invert_moves
from cube_app.metrics import solution_cost
from cube_app.native import NATIVE_EXE, native_solver_available
from cube_app.native import solve_native
from cube_app.native import NativeSolverCancelled, NativeSolverError, NativeSolverTimeout, _PERSISTENT_SOLVER, _PersistentNativeSolver, _validated_result


def quarter_turn_oracle(depth=3):
    """Independent QTM BFS, including consecutive turns of the same face."""
    distances = {CubieCube(): 0}
    pending = deque([CubieCube()])
    while pending:
        state = pending.popleft()
        distance = distances[state]
        if distance == depth:
            continue
        for move in range(18):
            if move % 3 == 1:
                continue
            child = state.apply_move_index(move)
            if child not in distances:
                distances[child] = distance + 1
                pending.append(child)
    return distances


class NativeBridgeValidationTests(unittest.TestCase):
    def test_result_requires_matching_metric_cost_and_valid_moves(self):
        cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        payload = {"metric": "QTM", "depth": 2, "moves": ["R2"], "optimal": True}
        self.assertEqual(_validated_result(cube, payload, "QTM")["depth"], 2)
        self.assertEqual(_validated_result(cube, {**payload, "asset_profile": "strong"}, "QTM")["asset_profile"], "strong")
        for update in ({"metric": "HTM"}, {"depth": 1}, {"depth": True}, {"moves": ["nonsense"]}, {"moves": ["U2"]}):
            with self.subTest(update=update), self.assertRaises(NativeSolverError):
                _validated_result(cube, {**payload, **update}, "QTM")

    def test_exhausted_budget_is_not_an_engine_failure(self):
        cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        result = _validated_result(cube, {"metric": "QTM", "depth": -1, "moves": [], "optimal": False, "status": "budget_exhausted"}, "QTM")
        self.assertIsNone(result["depth"])
        self.assertFalse(result["optimal"])

    def test_handshake_rejects_old_or_missing_capabilities(self):
        ready = {"ok": True, "type": "ready", "protocol_version": 3, "proof_version": 3, "metrics": ["HTM", "QTM"]}
        for update in ({"protocol_version": 2}, {"proof_version": 1}, {"metrics": ["HTM"]}, {"metrics": []}, {"metrics": None}):
            process = MagicMock()
            process.stdout = io.StringIO(json.dumps({**ready, **update}) + "\n")
            process.stderr = io.StringIO()
            process.poll.return_value = None
            bridge = _PersistentNativeSolver()
            with self.subTest(update=update), patch("cube_app.native.subprocess.Popen", return_value=process):
                with self.assertRaisesRegex(NativeSolverError, "capabilities"):
                    bridge._start_locked(None, None)
                self.assertIsNone(bridge._process)


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
    def test_sorted_slice_symmetry_enumerates_joint_coordinate(self):
        info = self.run_native("strong-symmetry-info")
        self.assertEqual(info["raw_sorted_slice"], 11880)
        self.assertEqual(info["classes"], 788)
        self.assertEqual(info["joint_entries"], 3_529_433_088)

    def test_all_moves_use_the_selected_metric(self):
        for move in range(18):
            cube = CubieCube().apply_move_index(move)
            for metric in ("HTM", "QTM"):
                result = self.run_native("solve", to_facelets(cube), "--metric", metric, "--threads", "1")
                self.assertEqual(result["metric"], metric)
                self.assertEqual(result["depth"], 2 if metric == "QTM" and move % 3 == 1 else 1)
                self.assertEqual(result["depth"], solution_cost(result["moves"], metric))
                verified = cube
                for name in result["moves"]:
                    verified = verified.apply_move_index(MOVE_INDEX[name])
                self.assertTrue(verified.is_solved())

    def test_qtm_oracle_matches_threads_and_inverse_direction(self):
        oracle = quarter_turn_oracle(4)
        for threads in (1, 4):
            for inverse in (False, True):
                for formula in ("R2", "R2 U", "R U F", "R U R'", "R2 F'", "R2 U2", "R U F2"):
                    cube = CubieCube()
                    for name in formula.split():
                        cube = cube.apply_move_index(MOVE_INDEX[name])
                    flags = ["--inverse-direction"] if inverse else []
                    result = self.run_native("solve", to_facelets(cube), "--metric", "QTM", "--threads", str(threads), *flags)
                    self.assertEqual(result["depth"], oracle[cube])
                    self.assertTrue(result["optimal"])
                    for name in result["moves"]:
                        cube = cube.apply_move_index(MOVE_INDEX[name])
                    self.assertTrue(cube.is_solved())

    def test_qtm_heuristic_is_admissible_against_quarter_turn_bfs(self):
        result = self.run_native("check-heuristic", "--depth", "3", "--metric", "QTM")
        self.assertEqual(result["checked"], len(quarter_turn_oracle()))

    def test_qtm_kernel_ablation_switches_preserve_exact_shallow_proof(self):
        cube = CubieCube()
        for name in ("R2", "U", "F"):
            cube = cube.apply_move_index(MOVE_INDEX[name])
        expected = quarter_turn_oracle(4)[cube]
        for flags in ((), ("--transposition",), ("--transposition", "--tt-every-node"),
                      ("--legacy-split",), ("--no-direction-probe",), ("--inverse-direction",)):
            with self.subTest(flags=flags):
                result = self.run_native("solve", to_facelets(cube), "--metric", "QTM",
                                         "--max-depth", str(expected), "--threads", "4",
                                         "--no-native-candidate", *flags)
                self.assertEqual(result["depth"], expected)
                self.assertTrue(result["optimal"])

    def test_qtm_partial_assets_are_metric_isolated_and_admissible(self):
        with tempfile.TemporaryDirectory(prefix="魔方 QTM 表-") as directory:
            corner = os.path.join(directory, "corner.pdb")
            phase1 = os.path.join(directory, "phase1.pdb")
            for command, path in (("build-corner-pdb", corner), ("build-phase1-pdb", phase1)):
                result = self.run_native(command, path, "--metric", "QTM", "--coverage-depth", "3", "--threads", "2")
                self.assertEqual(result["metric"], "QTM")
                self.assertFalse(result["complete"])
                self.assertEqual(result["coverage_depth"], 3)
            checked = self.run_native("check-heuristic", "--metric", "QTM", "--depth", "5",
                                      "--pdb", corner, "--phase1-pdb", phase1)
            self.assertEqual(checked["checked"], 105046)
            cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
            qtm = self.run_native("solve", to_facelets(cube), "--metric", "QTM",
                                  "--qtm-pdb", corner, "--qtm-phase1-pdb", phase1)
            self.assertEqual((qtm["depth"], qtm["corner_pdb_metric"], qtm["phase1_pdb_metric"]),
                             (2, "QTM", "QTM"))
            self.assertEqual(qtm["asset_profile"], "partial")
            self.assertFalse(qtm["corner_pdb_complete"])
            htm = self.run_native("solve", to_facelets(cube), "--metric", "HTM",
                                  "--qtm-pdb", corner, "--qtm-phase1-pdb", phase1)
            self.assertEqual(htm["depth"], 1)
            wrong_flag = subprocess.run([str(NATIVE_EXE), "solve", to_facelets(cube),
                                         "--metric", "QTM", "--pdb", corner],
                                        capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(wrong_flag.returncode, 0)
            with open(corner, "r+b") as asset:
                asset.seek(80)
                byte = asset.read(1)
                asset.seek(80)
                asset.write(bytes([byte[0] ^ 1]))
            corrupted = subprocess.run([str(NATIVE_EXE), "solve", to_facelets(cube),
                                        "--metric", "QTM", "--qtm-pdb", corner],
                                       capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(corrupted.returncode, 0)

    def test_qtm_budget_cannot_use_loaded_htm_tail(self):
        with tempfile.TemporaryDirectory(prefix="魔方 QTM 尾表-") as directory:
            path = os.path.join(directory, "tail.pdb")
            self.run_native("build-tail-pdb", path, "--depth", "1", "--threads", "2")
            cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
            for budget in (1, 2):
                result = self.run_native("solve", to_facelets(cube), "--metric", "QTM", "--max-depth", str(budget), "--tail-pdb", path)
                self.assertEqual(result["tail_queries"], 0)
                self.assertFalse(result["tail_enabled"])
                self.assertEqual(result["depth"], -1 if budget == 1 else 2)
                self.assertEqual(result["optimal"], budget == 2)

    def test_qtm_tail_uses_quarter_turn_distance_and_rejects_wrong_flag(self):
        with tempfile.TemporaryDirectory(prefix="魔方 QTM Tail-") as directory:
            path = os.path.join(directory, "tail_qtm.pdb")
            built = self.run_native("build-tail-pdb", path, "--metric", "QTM", "--depth", "4", "--threads", "2")
            self.assertEqual((built["metric"], built["version"]), ("QTM", 5))
            state = to_facelets(CubieCube().apply_move_index(MOVE_INDEX["R2"]))
            short = self.run_native("solve", state, "--metric", "QTM", "--max-depth", "1",
                                    "--qtm-tail-pdb", path)
            self.assertEqual(short["depth"], -1)
            result = self.run_native("solve", state, "--metric", "QTM", "--max-depth", "2",
                                     "--qtm-tail-pdb", path)
            self.assertEqual(result["depth"], 2)
            self.assertTrue(result["optimal"])
            self.assertGreater(result["tail_hits"], 0)
            wrong = subprocess.run([str(NATIVE_EXE), "solve", state, "--metric", "QTM",
                                    "--tail-pdb", path], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(wrong.returncode, 0)

    def test_cli_rejects_fractional_or_unsupported_budgets(self):
        for budget in ("2.5", "2x", "-1", "27"):
            process = subprocess.run([str(NATIVE_EXE), "solve", to_facelets(CubieCube()), "--metric", "QTM", "--max-depth", budget], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(process.returncode, 0)
            self.assertTrue(process.stderr.strip())

    def test_protocol_alternates_metrics_and_preserves_legacy_frames(self):
        with tempfile.TemporaryDirectory(prefix="魔方 QTM 协议-") as directory:
            path = os.path.join(directory, "tail.pdb")
            self.run_native("build-tail-pdb", path, "--depth", "1", "--threads", "2")
            process = subprocess.Popen([str(NATIVE_EXE), "serve", "--tail-pdb", path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                ready = json.loads(process.stdout.readline())
                self.assertEqual(ready["protocol_version"], 3)
                self.assertEqual(ready["proof_version"], 3)
                self.assertEqual(ready["metrics"], ["HTM", "QTM"])
                self.assertEqual(ready["assets"]["QTM"]["profile"], "fallback")
                state = to_facelets(CubieCube().apply_move_index(MOVE_INDEX["R2"]))
                def request(frame):
                    process.stdin.write(frame + "\n")
                    process.stdin.flush()
                    events = []
                    while True:
                        event = json.loads(process.stdout.readline())
                        if event.get("type") == "progress":
                            events.append(event)
                        else:
                            return event, events
                first, _ = request(f"solve\ta\t{state}\t1\t5\t2\tHTM\t")
                self.assertEqual(first["depth"], 1)
                second, events = request(f"solve\tb\t{state}\t1\t5\t2\tQTM\t")
                self.assertEqual(second["status"], "budget_exhausted")
                self.assertEqual(events[0]["completed_depth"], 1)
                self.assertEqual(second["tail_queries"], 0)
                third, _ = request(f"solve\tc\t{state}\t2\t5\t2\tQTM\t")
                self.assertEqual(third["depth"], 2)
                self.assertTrue(third["optimal"])
                fourth, _ = request(f"solve\td\t{state}\t1\t5\t2\t")
                self.assertEqual(fourth["metric"], "HTM")
                legacy, events = request(f"{state}\t1\t5\t2\t")
                self.assertEqual(legacy["metric"], "HTM")
                self.assertEqual(events[0]["completed_depth"], 0)
                invalid, _ = request(f"solve\tx\t{state}\t2\t5\t2\tWRONG\t")
                self.assertFalse(invalid["ok"])
            finally:
                process.stdin.close()
                process.wait(timeout=5)
                process.stdout.close()

    def test_coordinate_cache_corruption_is_rebuilt(self):
        with tempfile.TemporaryDirectory(prefix="魔方 缓存🧩-") as directory:
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

    def test_tail_database_builds_and_loads_in_unicode_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="魔方 尾表🧩-") as directory:
            path = os.path.join(directory, "tail.pdb")
            built = self.run_native("build-tail-pdb", path, "--depth", "1", "--threads", "2")
            self.assertEqual(built["depth"], 1)
            cube = CubieCube().apply_move_index(MOVE_INDEX["R"])
            result = self.run_native("solve", to_facelets(cube), "--max-depth", "1", "--tail-pdb", path)
            self.assertEqual(result["depth"], 1)
            self.assertTrue(result["optimal"])
            for name in result["moves"]:
                cube = cube.apply_move_index(MOVE_INDEX[name])
            self.assertTrue(cube.is_solved())

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
    def test_qtm_dynamic_incumbent_prefers_cost_over_formula_length(self):
        scramble = "B2 U' F U' L2 F' D F U B R F' U' F2".split()
        cube = CubieCube()
        for name in scramble:
            cube = cube.apply_move_index(MOVE_INDEX[name])
        solution = invert_moves(scramble)
        shorter_formula = solution + ["R2"] * 4
        lower_cost = solution + ["U", "U'", "R", "R'", "F", "F'"]
        self.assertLess(len(shorter_formula), len(lower_cost))
        self.assertGreater(solution_cost(shorter_formula, "QTM"), solution_cost(lower_cost, "QTM"))
        cancel = threading.Event()
        events = []
        def progress(event):
            events.append(event)
            if event["upper_bound"] == solution_cost(lower_cost, "QTM") - 1:
                cancel.set()
        with self.assertRaises(NativeSolverCancelled):
            solve_native(cube, metric="QTM", max_depth=26, timeout_seconds=10, incumbent_moves=shorter_formula,
                         incumbent_provider=lambda: lower_cost, cancel_event=cancel, threads=2, progress_callback=progress)
        self.assertTrue(any(event["upper_bound"] == solution_cost(lower_cost, "QTM") - 1 for event in events))

    def test_qtm_pdb_lower_bounds_match_independent_oracle(self):
        result = self.run_native("check-heuristic", "--depth", "3", "--metric", "QTM", "--pdb", ".cache/native/corner_htm_v2.pdb", "--phase1-pdb", ".cache/native/phase1_sym_htm_v2.pdb")
        self.assertEqual(result["checked"], len(quarter_turn_oracle()))
        self.assertGreater(result["small_pdb_queries"], 0)

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
        with tempfile.TemporaryDirectory(prefix="魔方 剪枝🧩-") as directory:
            path = os.path.join(directory, "partial.pdb")
            self.run_native("build-corner-pdb", path, "--coverage-depth", "0", "--threads", "2")
            phase1 = os.path.join(directory, "partial-phase1.pdb")
            self.run_native("build-phase1-pdb", phase1, "--coverage-depth", "0", "--threads", "2")
            result = self.run_native("check-heuristic", "--depth", "3", "--pdb", path, "--phase1-pdb", phase1)
            self.assertEqual(result["checked"], 3502)
            self.assertGreater(result["small_pdb_queries"], 0)
            qtm = self.run_native("check-heuristic", "--depth", "3", "--metric", "QTM", "--pdb", path, "--phase1-pdb", phase1)
            self.assertEqual(qtm["checked"], len(quarter_turn_oracle()))
            self.assertGreater(qtm["small_pdb_queries"], 0)

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

    def test_qtm_cancel_reuses_only_complete_layers_with_metric_isolation(self):
        cube = CubieCube()
        for name in "B2 U' F U' L2 F' D F U B R F' U' F2".split():
            cube = cube.apply_move_index(MOVE_INDEX[name])
        bridge = _PersistentNativeSolver()
        cancelled = threading.Event()
        events = []

        def cancel_after_complete_layer(event):
            events.append(event)
            if event["completed_depth"] >= 10 and event["completed_depth"] >= event["current_depth"]:
                cancelled.set()

        try:
            with self.assertRaises(NativeSolverCancelled):
                bridge.solve(cube, 26, 10, 2, None, cancelled, cancel_after_complete_layer, metric="QTM")
            self.assertTrue(cancelled.is_set())
            process = bridge._process
            self.assertIsNotNone(process)
            completed = events[-1]["completed_depth"]
            self.assertGreaterEqual(completed, 10)
            self.assertLess(completed, events[-1]["current_depth"])
            self.assertTrue(events[-1]["cancelled"])

            resumed = []
            retry_cancelled = threading.Event()

            def cancel_retry(event):
                resumed.append(event)
                retry_cancelled.set()

            with self.assertRaises(NativeSolverCancelled):
                bridge.solve(cube, 26, 10, 2, None, retry_cancelled, cancel_retry, metric="QTM")
            self.assertIs(bridge._process, process)
            self.assertGreaterEqual(resumed[0]["completed_depth"], completed)
            self.assertEqual(resumed[0]["current_depth"], resumed[0]["completed_depth"] + 1)
            self.assertTrue(all(event["metric"] == "QTM" for event in events + resumed))

            htm_events = []
            exhausted = bridge.solve(cube, 0, 10, 2, None, None, htm_events.append, metric="HTM")
            self.assertIs(bridge._process, process)
            self.assertEqual(exhausted["status"], "budget_exhausted")
            self.assertEqual(htm_events[0]["metric"], "HTM")
            self.assertEqual(htm_events[0]["completed_depth"], htm_events[0]["lower_bound"] - 1)
            self.assertLess(htm_events[0]["completed_depth"], completed)
        finally:
            bridge.close()

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
