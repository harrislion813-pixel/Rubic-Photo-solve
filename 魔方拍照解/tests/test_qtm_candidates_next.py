"""Independent candidate replay and Q2 timing/rollback contracts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost
from cube_app.solvers.qtm import native
from test_native_qtm import ROOT, environment, run
from test_native_qtm import binary as binary
from train_qtm_pgo import training_states
from train_htm_pgo import training_states as htm_training_states


@pytest.mark.qtm_native
@pytest.mark.qtm_full_assets
@pytest.mark.parametrize("schedule", ["legacy", "short-slices"])
def test_candidate_direction_statistics_and_independent_replay(binary, schedule):
    assert native.QTM_PHASE1_PDB.is_file(), "complete phase1 PDB required for Q2 gate"
    state = CubieCube()
    for move in "R U F".split():
        state = state.apply_move_index(MOVE_INDEX[move])
    result = run(binary, "fast-solve", to_facelets(state), "--qtm-phase1-pdb", native.QTM_PHASE1_PDB,
                 "--timeout", "1", f"--candidate-schedule={schedule}")
    for move in result["moves"]:
        state = state.apply_move_index(MOVE_INDEX[move])
    assert state.is_solved() and solution_cost(result["moves"], "QTM") == result["cost"]
    directions = result["candidate_directions"]
    assert [item["direction"] for item in directions] == list(range(6))
    assert sum(item["phase1_nodes"] for item in directions) == result["phase1_nodes"]
    assert sum(item["phase2_nodes"] for item in directions) == result["phase2_nodes"]
    assert sum(item["elapsed_seconds"] for item in directions) <= result["elapsed_seconds"] + .0001
    assert all(item["visits"] <= (2 if schedule == "short-slices" else 1) for item in directions)
    for item in directions:
        costs = [change["cost"] for change in item["improvements"]]
        assert all(left > right for left, right in zip(costs, costs[1:]))
        if costs:
            assert item["first_cost"] == costs[0] and item["best_cost"] == costs[-1]
            assert 0 <= item["first_candidate_seconds"] <= result["elapsed_seconds"]


def test_q2_defaults_and_independent_rollback_switches(monkeypatch):
    for name in ("CUBE_QTM_CANDIDATE_SCHEDULE", "CUBE_QTM_LATE_TAIL_IMPROVEMENT", "CUBE_QTM_EXPANSION"):
        monkeypatch.delenv(name, raising=False)
    bridge = native._PersistentNativeSolver()
    command = bridge._command()
    assert "--candidate-schedule=legacy" in command
    assert "--late-tail-improvement=off" in command and "--qtm-expansion=generic" in command
    monkeypatch.setenv("CUBE_QTM_CANDIDATE_SCHEDULE", "short-slices")
    monkeypatch.setenv("CUBE_QTM_LATE_TAIL_IMPROVEMENT", "on")
    monkeypatch.setenv("CUBE_QTM_EXPANSION", "full-strong")
    changed = bridge._command()
    assert "--candidate-schedule=short-slices" in changed and "--late-tail-improvement=on" in changed
    assert "--qtm-expansion=full-strong" in changed


def test_pgo_training_excludes_every_frozen_acceptance_state():
    cases = json.loads((ROOT / "tests/qtm_pgo_cases.json").read_text(encoding="utf-8"))
    initials = json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))
    assert len(training_states(cases, initials)) == 8
    overlap = [{"name": "initial-1", "scramble": "R"}]
    with pytest.raises(ValueError, match="independent explicit scrambles"):
        training_states(overlap, initials)
    htm_cases = json.loads((ROOT / "tests/htm_pgo_cases.json").read_text(encoding="utf-8"))
    assert len(htm_training_states(htm_cases, initials)) == 8
    with pytest.raises(ValueError, match="independent explicit scrambles"):
        htm_training_states(overlap, initials)


@pytest.fixture(scope="module")
def tail_gate_binary(tmp_path_factory):
    compiler = shutil.which(os.environ.get("CXX", "g++")) or r"C:\msys64\ucrt64\bin\g++.exe"
    assert Path(compiler).is_file(), "the real Tail gate requires its portable C++ harness compiler"
    target = tmp_path_factory.mktemp("qtm-tail-gate") / "tail_gate.exe"
    command = [compiler, "-std=c++20", "-O0", "-march=x86-64", "-mtune=generic", "-I", "include",
               "../../tests/qtm_tail_gate.cpp", *[f"src/{name}.cpp" for name in
                ("cube", "fast", "pdb", "solver", "symmetry", "strong_coords", "strong_pdb", "tail")],
               "-pthread", "-static", "-municode", "-o", os.path.relpath(target, ROOT / "native/qtm")]
    compiled = subprocess.run(command, cwd=ROOT / "native/qtm", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=180)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return target


@pytest.mark.qtm_native
@pytest.mark.qtm_full_assets
def test_real_late_tail_replacement_quota_cancellation_and_deadline(tail_gate_binary):
    assert native.QTM_TAIL_PDB_8.is_file(), "the late Tail gate cannot silently skip its complete asset"
    process = subprocess.run([str(tail_gate_binary), str(native.QTM_TAIL_PDB_8)], env=environment(),
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads(process.stdout)
    assert len(result["direct"]) == 4 and len(result["solves"]) == 9
    from cube_app.cubie import from_facelets
    for event in result["direct"] + result["solves"]:
        state = from_facelets(event["facelets"])
        for move in event["moves"]:
            state = state.apply_move_index(MOVE_INDEX[move])
        assert state.is_solved()
        assert solution_cost(event["moves"], "QTM") == event.get("cost", event.get("depth"))
    for event in result["solves"]:
        assert event["attempts"] == 1 and event["window_replacements"] > 0
        assert event["max_reserved"] <= event["threads"]
