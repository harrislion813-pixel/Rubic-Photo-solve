"""Independent QTM protocol, shallow oracle and staged-proof release gates."""

from __future__ import annotations

import json
import os
import queue
import random
import struct
import subprocess
import threading
from collections import deque
from pathlib import Path

import pytest

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost
from cube_app.solvers.qtm import native

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.qtm_native


@pytest.fixture(scope="module")
def binary():
    path = Path(os.environ.get("QTM_TEST_BINARY", str(native.NATIVE_EXE))).resolve()
    if not path.is_file():
        if os.environ.get("REQUIRE_QTM_BINARY") == "1":
            pytest.fail(f"required QTM executable missing: {path}")
        pytest.skip("independent QTM executable is not installed")
    return path


def environment():
    return {**os.environ, "CUBE_NATIVE_COORDINATE_CACHE": str(ROOT / ".cache/qtm/coordinates_dual_v2.bin")}


def run(binary, *args):
    completed = subprocess.run([str(binary), *map(str, args)], env=environment(),
                               capture_output=True, text=True, encoding="utf-8", timeout=25)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


class Service:
    def __init__(self, binary, *args):
        self.process = subprocess.Popen([str(binary), "serve", *map(str, args)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env=environment(), text=True, encoding="utf-8",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.lines = queue.Queue()
        self.errors = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.error_reader = threading.Thread(target=self._read_errors, daemon=True)
        self.reader.start()
        self.error_reader.start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(json.loads(line))
        self.lines.put(None)

    def _read_errors(self):
        self.errors.extend(self.process.stderr)

    def send(self, *fields):
        self.process.stdin.write("\t".join(map(str, fields)) + "\n")
        self.process.stdin.flush()

    def event(self, kind=None, timeout=25):
        while True:
            event = self.lines.get(timeout=timeout)
            assert event is not None, "".join(self.errors)
            if kind is None or event.get("type") == kind:
                return event

    def solve(self, state, bound=26, timeout=2, threads=2, request_id="oracle"):
        self.send("solve", request_id, to_facelets(state), bound, timeout, threads, "QTM", "")
        return self.event("result")

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.process.terminate()
        self.process.wait(timeout=5)
        self.reader.join(2)
        self.error_reader.join(2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def oracle(depth):
    # Unit quarter turns provide an independent QTM shortest-path oracle.
    solved = CubieCube()
    seen = {to_facelets(solved): (solved, 0)}
    frontier = deque([(solved, 0)])
    quarter_turns = [index for index in range(18) if index % 3 != 1]
    while frontier:
        state, distance = frontier.popleft()
        if distance == depth:
            continue
        for index in quarter_turns:
            child = state.apply_move_index(index)
            key = to_facelets(child)
            if key not in seen:
                seen[key] = (child, distance + 1)
                frontier.append((child, distance + 1))
    return list(seen.values())


def replay(state, result, expected):
    assert result["metric"] == "QTM" and result["optimal"]
    assert solution_cost(result["moves"], "QTM") == result["depth"] == expected
    for move in result["moves"]:
        state = state.apply_move_index(MOVE_INDEX[move])
    assert state.is_solved()


def test_independent_oracle_and_half_turn_cost(binary):
    states = oracle(3)
    assert len(states) == 1195
    checked = run(binary, "check-heuristic", "--metric", "QTM", "--depth", "3")
    assert checked["ok"] and checked["checked"] == len(states)
    with Service(binary, "--no-native-candidate", "--no-proof-cache", "--direction-policy=off") as service:
        assert service.event("ready")["metrics"] == ["QTM"]
        for state, depth in random.Random(20261001).sample(states, 24):
            replay(state, service.solve(state, bound=depth), depth)
        state = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        replay(state, service.solve(state, bound=2), 2)
        excluded = service.solve(state, bound=1)
        assert not excluded["optimal"] and excluded["depth"] == -1
        for threads in (1, 2, 3):
            replay(state, service.solve(state, bound=2, timeout=0, threads=threads), 2)


@pytest.mark.parametrize("mode", ["legacy", "fused", "split"])
def test_complete_nibble_scan_and_original_fnv(binary, tmp_path, mode):
    data = bytes(value for value in range(256) if value & 15 < 15 and value >> 4 < 15) * 13
    path = tmp_path / "chunk.bin"
    path.write_bytes(data)
    expected = 1469598103934665603
    for value in data:
        expected = ((expected ^ value) * 1099511628211) & ((1 << 64) - 1)
    checked = run(binary, "check-strong-chunk", path, f"--strong-validation={mode}")
    assert checked["valid"] and checked["maximum"] == 14 and checked["checksum"] == expected
    for invalid in (0x0F, 0xF0, 0xFF):
        path.write_bytes(data + bytes([invalid]))
        assert not run(binary, "check-strong-chunk", path, f"--strong-validation={mode}")["valid"]
    path.write_bytes(data)
    assert not run(binary, "check-strong-chunk", path, "--coverage-depth", "13", f"--strong-validation={mode}")["valid"]


@pytest.fixture(scope="module")
def partial_assets(binary, tmp_path_factory):
    directory = tmp_path_factory.mktemp("qtm-partial")
    paths = {name: directory / (name + ".pdb") for name in ("corner", "phase1", "fallback")}
    run(binary, "build-corner-pdb", paths["corner"], "--metric", "QTM", "--coverage-depth", "0", "--threads", "2")
    run(binary, "build-phase1-pdb", paths["phase1"], "--metric", "QTM", "--coverage-depth", "0", "--threads", "2")
    run(binary, "build-corner-pdb", paths["fallback"], "--metric", "HTM", "--coverage-depth", "0", "--threads", "2")
    return paths


def test_partial_assets_retain_legal_small_bounds(binary, partial_assets):
    with Service(binary, "--qtm-pdb", partial_assets["corner"], "--qtm-phase1-pdb", partial_assets["phase1"],
                 "--fallback-pdb", partial_assets["fallback"], "--no-native-candidate") as service:
        ready = service.event("ready")
        assert ready["assets"]["QTM"]["profile"] == "partial"
        assert not ready["assets"]["QTM"]["corner_complete"]
        assert "fallback_corner" not in {step["asset"] for step in ready["initialization_steps"]}
        for state, depth in random.Random(81).sample(oracle(2), 8):
            replay(state, service.solve(state, bound=depth), depth)


def test_corrupt_main_asset_loads_explicit_fallback(binary, partial_assets, tmp_path):
    corrupt = tmp_path / "corner.pdb"
    corrupt.write_bytes(b"bad QTM asset")
    with Service(binary, "--qtm-pdb", corrupt, "--fallback-pdb", partial_assets["fallback"],
                 "--no-native-candidate") as service:
        ready = service.event("ready")
        assert ready["assets"]["QTM"]["profile"] == "fallback"
        steps = {step["asset"]: step for step in ready["initialization_steps"]}
        assert steps["qtm_corner"]["error"] and steps["qtm_corner"]["mapped_bytes"] == 0
        assert steps["fallback_corner"]["mapped_bytes"] > 0
        state = CubieCube().apply_move_index(MOVE_INDEX["F2"])
        replay(state, service.solve(state, bound=2), 2)


@pytest.mark.parametrize("outcome", ["cancel", "deadline", "deny", "corrupt"])
def test_waiting_strong_preserves_incomplete_cost(binary, tmp_path, outcome):
    corrupt = tmp_path / "strong.pdb"
    corrupt.write_bytes(b"bad strong asset" * 8)
    with Service(binary, "--strong-pdb", corrupt, "--asset-loading=staged", "--loader-managed",
                 "--loader-threads", "1", "--loader-budget=shared", "--proof-schedule=strong-first",
                 "--base-proof-window=0", "--no-native-candidate", "--no-proof-cache") as service:
        service.event("ready")
        service.event("loader_stage")
        state = CubieCube()
        case = next(item for item in json.loads((ROOT / "tests/native_cases.json").read_text(encoding="utf-8"))
                    if item["name"] == "known18")
        for move in case["scramble"].split():
            state = state.apply_move_index(MOVE_INDEX[move])
        service.send("solve", "wait", to_facelets(state), 26, .4, 3, "QTM", "")
        waiting = service.event("progress")
        while waiting.get("phase") != "waiting_strong":
            waiting = service.event("progress")
        if outcome == "cancel":
            service.send("cancel", "wait")
        elif outcome == "deny":
            service.send("loader_deny", "test")
        elif outcome == "corrupt":
            service.send("loader_resume", "test")
        result = service.event("result")
        assert not result["optimal"]
        if outcome in {"cancel", "deadline"}:
            assert result["completed_depth"] == waiting["completed_depth"]
        assert result["status"] == ("cancelled" if outcome == "cancel" else "timeout")
        assert result["strong_wait_seconds"] < 1


@pytest.mark.qtm_full_assets
def test_full_strong_gate(binary):
    paths = (native.QTM_CORNER_PDB, native.QTM_PHASE1_PDB, native.QTM_STRONG_PDB_NIBBLE, native.QTM_TAIL_PDB_8)
    if not all(path.is_file() for path in paths):
        if os.environ.get("REQUIRE_QTM_STRONG") == "1":
            pytest.fail("complete QTM release assets are required for this gate")
        pytest.skip("full strong assets belong to the separate release gate")
    result = run(binary, "check-heuristic", "--metric", "QTM", "--depth", "3",
                 "--pdb", paths[0], "--phase1-pdb", paths[1], "--strong-pdb", paths[2])
    assert result["ok"] and result["checked"] == 1195
    with Service(binary, "--qtm-pdb", paths[0], "--qtm-phase1-pdb", paths[1], "--strong-pdb", paths[2],
                 "--qtm-tail-pdb", paths[3], "--strong-validation=split", "--loader-threads", "4") as service:
        assert service.event("ready")["assets"]["QTM"]["profile"] == "strong"
        for state, depth in random.Random(20261002).sample(oracle(3), 8):
            replay(state, service.solve(state, bound=depth), depth)


@pytest.mark.qtm_full_assets
@pytest.mark.parametrize("damage", ["truncated", "metric", "coverage", "chunk", "eager"])
def test_damaged_strong_never_publishes_a_snapshot(binary, tmp_path, request, damage):
    source = native.QTM_STRONG_PDB_NIBBLE
    if not source.is_file() or not native.QTM_CORNER_PDB.is_file() or not native.QTM_PHASE1_PDB.is_file():
        if os.environ.get("REQUIRE_QTM_STRONG") == "1":
            pytest.fail("complete QTM release assets are required for corruption checks")
        pytest.skip("full strong release assets are not installed")
    with source.open("rb") as stream:
        header = bytearray(stream.read(296))
    if damage == "metric":
        struct.pack_into("<I", header, 16, 1)
    elif damage == "coverage":
        struct.pack_into("<I", header, 40, 2)
    corrupt = tmp_path / "strong.pdb"
    request.addfinalizer(lambda: corrupt.unlink(missing_ok=True))
    with corrupt.open("wb") as stream:
        stream.write(header)
        if damage != "truncated":
            # A zero body has valid dimensions but incorrect chunk checksums.
            stream.truncate(source.stat().st_size)
    with Service(binary, "--qtm-pdb", native.QTM_CORNER_PDB, "--qtm-phase1-pdb", native.QTM_PHASE1_PDB,
                 "--strong-pdb", corrupt, f"--asset-loading={'eager' if damage == 'eager' else 'staged'}", "--strong-validation=split",
                 "--loader-threads", "4") as service:
        ready = service.event("ready")
        assert ready["assets"]["QTM"]["profile"] == "base"
        if damage == "eager":
            assert any(step["asset"] == "strong" and step["error"] for step in ready["initialization_steps"])
        else:
            error = service.event("asset_error")
            assert error["stage"] == "strong"
        state = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        result = service.solve(state, bound=2)
        assert result["asset_profile"] == "base" and not result["strong_pdb"]
        replay(state, result, 2)


@pytest.mark.parametrize("threads", [1, 2, 3])
def test_native_small_thread_quota_uses_explicit_base_policy(binary, tmp_path, threads):
    corrupt = tmp_path / "strong.pdb"
    corrupt.write_bytes(b"invalid" * 12)
    with Service(binary, "--strong-pdb", corrupt, "--asset-loading=staged", "--loader-managed",
                 "--loader-threads", "1", "--loader-budget=shared", "--proof-schedule=strong-first",
                 "--base-proof-window=0", "--no-native-candidate") as service:
        service.event("ready")
        service.event("loader_stage")
        case = next(item for item in json.loads((ROOT / "tests/native_cases.json").read_text(encoding="utf-8"))
                    if item["name"] == "known18")
        state = CubieCube()
        for move in case["scramble"].split():
            state = state.apply_move_index(MOVE_INDEX[move])
        service.send("solve", "small", to_facelets(state), 26, .2, threads, "QTM", "")
        phases = []
        while True:
            event = service.event()
            if event.get("type") == "thread_activity":
                assert event["proof"] + event["candidate"] + event["loader_reserved"] <= threads
            if event.get("type") == "progress":
                phases.append(event["phase"])
            if event.get("type") == "result":
                assert event["status"] == "timeout" and not event["optimal"]
                break
        assert ("waiting_strong" in phases) == (threads >= 3)
