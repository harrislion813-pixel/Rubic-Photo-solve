"""Synthetic evidence gates; these tests launch no solver or asset loader."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

import summarize_next_speed as summary
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets


@pytest.fixture
def matrix(tmp_path, monkeypatch):
    facelets = to_facelets(CubieCube().apply_move_index(MOVE_INDEX["R"]))
    digest = hashlib.sha256(facelets.encode()).hexdigest()
    frozen = [{"name": name, "facelets": facelets, "known_optimal_costs": {"HTM": 1, "QTM": 1}}
              for name in summary.STATES]
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/initial_solver_cases.json").write_text(json.dumps(frozen), encoding="utf-8")
    monkeypatch.setattr(summary, "ROOT", tmp_path)
    report = {"cases": [], "failures": []}
    for repeat, labels in enumerate((("baseline", "current"), ("current", "baseline"), ("baseline", "current"))):
        for name in summary.STATES:
            for metric in summary.METRICS:
                for label in labels:
                    seconds = 10 if label == "baseline" else 8
                    answer = {"moves": ["R'"], "depth": 1, "metric": metric, "optimal": True}
                    terminal = {"status": "complete", "result": answer, "terminal_seconds": seconds}
                    report["cases"].append({"name": name, "metric": metric, "label": label, "repeat": repeat,
                        "facelets": facelets, "faceletsSha256": digest, "afterCleanup": terminal,
                        "events": [{"seconds": seconds + 1, "data": terminal}], "pageWallSeconds": seconds + 1,
                        "newProcess": True, "processTreeStopped": True, "solveRequests": 1,
                        "memory": {"scope": summary.MEMORY_SCOPE, "native_process_lifetime_peak_bytes": 100,
                                   "tree_sampled_peak_working_set_bytes": 200}})
    return report


def find(report, label="current", repeat=0):
    return next(case for case in report["cases"] if case["name"] == "initial-1"
                and case["metric"] == "HTM" and case["label"] == label and case["repeat"] == repeat)


def test_complete_matrix_uses_terminal_time_and_fixed_pairs(matrix):
    result = summary.summarize(matrix)
    assert result["matrix_complete"] and result["fixed_pair_order_valid"] and result["all_requests_fresh"]
    assert result["summary"]["HTM"]["par2_mean_seconds"] == {"baseline": 10, "current": 8}
    assert result["summary"]["HTM"]["adoption_gates_met"]
    assert result["records"][0]["page_observation_delay_seconds"] == 1


def test_missing_terminal_cannot_use_native_elapsed_resource_hold_or_page_time(matrix):
    case = find(matrix)
    case["afterCleanup"].pop("terminal_seconds")
    case["afterCleanup"].update(elapsed_seconds=0.001, resource_hold_seconds=0.1, request_elapsed_seconds=8)
    result = summary.summarize(matrix)
    record = next(r for r in result["records"] if r["name"] == "initial-1" and r["metric"] == "HTM"
                  and r["label"] == "current" and r["repeat"] == 0)
    assert not record["strict_success"] and record["par2_seconds"] == 60 and record["strict_seconds"] is None
    assert result["validation_errors"]


def test_repeated_formula_still_validates_later_cost_claim(matrix):
    case = find(matrix)
    correct = {"moves": ["R'"], "depth": 1, "metric": "HTM", "optimal": False}
    wrong = {**correct, "cost": 2, "optimal": True}
    case["events"] = [{"seconds": 1, "data": correct}, {"seconds": 2, "data": wrong}]
    result = summary.summarize(matrix)
    assert result["validation_errors"] and not result["summary"]["HTM"]["adoption_gates_met"]


def test_new_timeout_is_paired_even_when_success_counts_match(matrix):
    find(matrix, "current", 0)["afterCleanup"]["status"] = "timeout"
    find(matrix, "baseline", 1)["afterCleanup"]["status"] = "timeout"
    state = summary.summarize(matrix)["summary"]["HTM"]["per_state"]["initial-1"]
    assert state["new_timeout_repeats"] == [0]
    assert len(state["completed_pair_ratios"]) == 1


def test_timeout_keeps_valid_candidate_and_full_par2_penalty(matrix):
    case = find(matrix)
    case["afterCleanup"].update(status="timeout", optimal=False, terminal_seconds=30.1)
    case["afterCleanup"]["result"]["optimal"] = False
    case["events"].insert(0, {"seconds": 0.75, "data": {"moves": [], "depth": None, "optimal": False}})
    result = summary.summarize(matrix)
    record = next(r for r in result["records"] if r["name"] == "initial-1" and r["metric"] == "HTM"
                  and r["label"] == "current" and r["repeat"] == 0)
    assert record["par2_seconds"] == 60 and record["candidate_cost"] == 1
    assert record["first_delivery_seconds"] == 9
    assert not record["validation_errors"]


def test_resource_scope_and_five_percent_growth_are_required(matrix):
    for case in matrix["cases"]:
        if case["label"] == "current":
            case["memory"]["native_process_lifetime_peak_bytes"] = 106
    result = summary.summarize(matrix)
    assert not result["summary"]["HTM"]["resource_growth_within_5pct"]
    assert not result["summary"]["HTM"]["adoption_gates_met"]
    matrix["cases"][0]["memory"]["scope"] = "sampled_working_set"
    assert not summary.summarize(matrix)["summary"]["HTM"]["all_memory_samples_comparable"]


def test_complete_count_does_not_hide_duplicates_or_wrong_pair_order(matrix):
    wrong_order = copy.deepcopy(matrix)
    wrong_order["cases"].reverse()
    assert not summary.summarize(wrong_order)["fixed_pair_order_valid"]
    matrix["cases"][-1] = copy.deepcopy(matrix["cases"][0])
    result = summary.summarize(matrix)
    assert not result["matrix_complete"] and result["duplicate_runs"] == 1


def test_first_delivery_curve_does_not_treat_internal_events_as_page_delivery(matrix):
    case = find(matrix)
    case["events"].insert(0, {"seconds": 0.75, "data": {"moves": [], "depth": None,
        "timing_events": [{"event": "candidate_generated", "elapsed_seconds": 0.1, "cost": 1, "moves": ["R'"]}]}})
    state = summary.summarize(matrix)["summary"]["HTM"]["per_state"]["initial-1"]
    assert state["first_delivery_medians"]["current"] == 9
    run = next(r for r in state["all_runs"] if r["label"] == "current" and r["repeat"] == 0)
    assert run["first_generated_seconds"] == 0.1 and run["first_delivery_seconds"] == 9


def test_timeout_bounds_keep_only_completed_layers_and_do_not_change_par2(matrix):
    case = find(matrix)
    terminal = case["afterCleanup"]
    terminal.update(status="timeout", optimal=False, terminal_seconds=30.1,
                    progress={"completed_depth": 0, "current_depth": 2, "lower_bound": 0})
    terminal["result"].update(moves=["R'", "U", "U'"], depth=3, optimal=False)
    result = summary.summarize(matrix)
    record = next(r for r in result["records"] if r["name"] == "initial-1" and r["metric"] == "HTM"
                  and r["label"] == "current" and r["repeat"] == 0)
    assert record["completed_depth"] == 0 and record["completed_depth_source"] == "progress"
    assert record["proven_lower_bound"] == 1 and record["proof_gap"] == 2
    assert not record["strict_success"] and record["par2_seconds"] == 60
    assert not record["validation_errors"]


def test_active_layer_cannot_supply_a_missing_lower_bound():
    terminal = {"status": "timeout", "progress": {"current_depth": 20, "lower_bound": 1}}
    bounds = summary.proof_bounds(terminal, {}, 3)
    assert bounds["completed_depth"] is None and bounds["proven_lower_bound"] == 1
    assert bounds["proof_gap"] == 2 and bounds["proven_lower_bound_source"] == "progress.lower_bound"
    terminal["progress"].pop("lower_bound")
    bounds = summary.proof_bounds(terminal, {}, 3)
    assert bounds["completed_depth"] is None and bounds["proven_lower_bound"] is None
    assert bounds["proof_gap"] is None
