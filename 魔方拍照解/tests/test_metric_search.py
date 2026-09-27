"""Exact shallow oracles built independently of the production search/pruning."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import heapq
import itertools
from pathlib import Path
import random
import threading
import time

import pytest

from cube_app.cubie import CubieCube, CubeStateError, MOVE_INDEX, MOVE_NAMES
from cube_app.metrics import solution_cost
import cube_app.optimal as optimal

ROOT = Path(__file__).resolve().parents[1]
QUARTER_MOVES = tuple(i for i, name in enumerate(MOVE_NAMES) if not name.endswith("2"))


def apply_moves(cube, moves):
    for move in moves:
        cube = cube.apply_move_index(MOVE_INDEX[move] if isinstance(move, str) else move)
    return cube


def oracle_ball(cube, metric, radius):
    """Unrestricted unit BFS: QTM explicitly allows consecutive same-face turns."""
    indices = range(18) if metric == "HTM" else QUARTER_MOVES
    paths = {cube: ()}
    queue = deque([cube])
    while queue:
        state = queue.popleft()
        path = paths[state]
        if len(path) == radius:
            continue
        for index in indices:
            child = state.apply_move_index(index)
            if child not in paths:
                paths[child] = path + (index,)
                queue.append(child)
    return paths


@lru_cache(maxsize=None)
def solved_ball(metric, radius):
    return oracle_ball(CubieCube(), metric, radius)


def oracle_distance(cube, metric, radius):
    """Bidirectional unrestricted BFS proves every distance up to 2 * radius."""
    reference = solved_ball(metric, radius)
    target = oracle_ball(cube, metric, radius)
    distances = [len(path) + len(reference[state]) for state, path in target.items() if state in reference]
    return min(distances) if distances else None


@pytest.fixture(scope="module")
def solver():
    return optimal.OptimalSolver(ROOT / ".cache")


@pytest.mark.parametrize("metric", ["HTM", "QTM"])
def test_serial_matches_independent_shallow_bfs(solver, metric):
    oracle = solved_ball(metric, 3)
    rng = random.Random(28092026)
    samples = [CubieCube()]
    for depth in range(1, 4):
        layer = [state for state, path in oracle.items() if len(path) == depth]
        samples.extend(rng.sample(layer, min(12, len(layer))))
    samples.extend(apply_moves(CubieCube(), [face + "2"]) for face in "URFDLB")
    for cube in samples:
        expected = len(oracle[cube])
        result = solver.solve_cube(cube, max_depth=expected, timeout_seconds=5, metric=metric)
        assert result.metric == metric
        assert result.optimal and result.depth == expected
        assert solution_cost(result.moves, metric) == expected
        assert apply_moves(cube, result.moves).is_solved()


@pytest.mark.parametrize("metric", ["HTM", "QTM"])
def test_canonical_successors_preserve_full_shallow_oracle(metric):
    """Exhaustively validate same-face/opposite-face pruning through cost three."""
    reference = solved_ball(metric, 3)
    sequence = itertools.count()
    frontier = [(0, next(sequence), CubieCube(), 6)]
    contexts = {(CubieCube(), 6): 0}
    distances = {CubieCube(): 0}
    while frontier:
        cost, _, cube, last_face = heapq.heappop(frontier)
        if contexts[(cube, last_face)] != cost:
            continue
        for index, face in optimal._ALLOWED_MOVES[last_face]:
            next_cost = cost + (2 if metric == "QTM" and MOVE_NAMES[index].endswith("2") else 1)
            if next_cost > 3:
                continue
            child = cube.apply_move_index(index)
            context = (child, face)
            if next_cost < contexts.get(context, 4):
                contexts[context] = next_cost
                heapq.heappush(frontier, (next_cost, next(sequence), child, face))
            distances[child] = min(distances.get(child, 4), next_cost)
    assert distances == {state: len(path) for state, path in reference.items()}


def test_htm_heuristic_is_admissible_for_qtm_oracle(solver):
    # These tables keep their HTM semantics; rotation maxima remain lower bounds.
    for cube, path in solved_ball("QTM", 3).items():
        assert solver._prepare_phase1_state(cube, solver.tables)[-1] <= len(path)


def test_half_turn_budget_and_weighted_incumbent(solver):
    cube = apply_moves(CubieCube(), ["R2"])
    with pytest.raises(CubeStateError, match="QTM 1"):
        solver.solve_cube(cube, max_depth=1, metric="QTM")
    result = solver.solve_cube(cube, max_depth=2, metric="QTM")
    assert result.depth == 2 and result.optimal
    assert apply_moves(cube, result.moves).is_solved()
    with pytest.raises(ValueError, match="upper_bound"):
        solver.solve_cube(cube, metric="QTM", incumbent_moves=["R2"], upper_bound=1)
    result = solver.solve_cube(cube, metric="QTM", incumbent_moves=["R2"], upper_bound=2)
    assert result.depth == 2 and result.optimal


@pytest.mark.parametrize("sequence", [["R2", "U2"], ["R", "U", "F2"], ["F2", "L2"], ["R", "U", "R'", "U'"]])
def test_serial_weighted_phase1_and_phase2_match_bfs(solver, sequence):
    cube = apply_moves(CubieCube(), sequence)
    expected = oracle_distance(cube, "QTM", 2)
    result = solver.solve_cube(cube, max_depth=expected, metric="QTM", timeout_seconds=5)
    assert result.optimal and result.depth == expected
    assert apply_moves(cube, result.moves).is_solved()


def test_insufficient_budget_candidate_is_unproved(solver):
    cube = apply_moves(CubieCube(), ["R2"])
    result = solver.solve_cube(cube, max_depth=0, metric="QTM", incumbent_moves=["R2"])
    assert result.depth == 2 and result.metric == "QTM" and not result.optimal
    assert apply_moves(cube, result.moves).is_solved()
    with pytest.raises(CubeStateError, match="预算"):
        solver.solve_cube(cube, max_depth=0, metric="QTM")


def test_parallel_qtm_matches_oracle_and_filtered_root_count(monkeypatch):
    monkeypatch.setattr(optimal, "_PARALLEL_MIN_DEPTH", 1)
    solver = optimal.OptimalSolver(ROOT / ".cache", parallel=True, max_workers=2)
    events = []
    for sequence in (["R2"], ["R", "U", "F2"]):
        cube = apply_moves(CubieCube(), sequence)
        expected = oracle_distance(cube, "QTM", 2)
        result = solver.solve_cube(cube, metric="QTM", max_depth=expected, timeout_seconds=15, progress_callback=events.append)
        assert result.depth == expected and result.optimal and result.metric == "QTM"
        assert apply_moves(cube, result.moves).is_solved()
    assert any(event.get("found") is False and event["completed_depth"] == 1 for event in events)
    assert all(event["metric"] == "QTM" for event in events)


def test_parallel_permission_failure_preserves_qtm(monkeypatch):
    monkeypatch.setattr(optimal, "_PARALLEL_MIN_DEPTH", 1)
    class DeniedContext:
        def Pool(self, **kwargs):
            raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(optimal.multiprocessing, "get_context", lambda _: DeniedContext())
    solver = optimal.OptimalSolver(ROOT / ".cache", parallel=True, max_workers=2)
    events = []
    result = solver.solve_cube(apply_moves(CubieCube(), ["R2"]), metric="QTM", progress_callback=events.append)
    assert result.depth == 2 and result.metric == "QTM" and result.optimal
    assert any(event.get("parallel_fallback") for event in events)


def test_cancellation_keeps_only_completed_cost_layers(solver):
    event = threading.Event()
    progress = []
    def on_progress(snapshot):
        progress.append(snapshot)
        if snapshot.get("found") is False and snapshot["completed_depth"] == 1:
            event.set()
    with pytest.raises(optimal.SearchCancelled):
        solver.solve_cube(apply_moves(CubieCube(), ["R2"]), metric="QTM", cancel_event=event, progress_callback=on_progress)
    assert max(snapshot["completed_depth"] for snapshot in progress) == 1
    assert all(snapshot["metric"] == "QTM" for snapshot in progress)


def test_expired_deadline_prevents_incumbent_proof(solver):
    with pytest.raises(optimal.SearchTimeout):
        solver.solve_cube(apply_moves(CubieCube(), ["R2"]), metric="QTM", incumbent_moves=["R2"], deadline=time.monotonic() - 1)


def test_metric_is_per_request_on_shared_solver(solver):
    cube = apply_moves(CubieCube(), ["R2"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda metric: solver.solve_cube(cube, metric=metric), ["HTM", "QTM", "HTM"]))
    assert [(result.metric, result.depth) for result in results] == [("HTM", 1), ("QTM", 2), ("HTM", 1)]


def test_entrypoints_and_validation_on_zero_step(solver):
    from cube_app.cubie import to_facelets
    for metric in ("HTM", "QTM"):
        assert solver.solve_facelets(to_facelets(CubieCube()), metric=metric).metric == metric
        assert optimal.solve(to_facelets(CubieCube()), metric=metric).metric == metric
    for metric, budget in [("STM", 0), ("QTM", 27), ("HTM", 21), ("QTM", 1.0)]:
        with pytest.raises(ValueError):
            solver.solve_cube(CubieCube(), max_depth=budget, metric=metric)
