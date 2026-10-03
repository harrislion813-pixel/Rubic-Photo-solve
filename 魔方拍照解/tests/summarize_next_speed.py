"""Replay every formula claim and summarize the fixed paired 72-request matrix."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cube_app.cubie import MOVE_INDEX, from_facelets  # noqa: E402
from cube_app.metrics import solution_cost  # noqa: E402

STATES = ("initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16")
LABELS = ("baseline", "current")
METRICS = ("HTM", "QTM")
MEMORY_SCOPE = "launcher_descendant_native_process_lifetime_peak"


def finite(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def ratio(current, baseline):
    return current / baseline if current is not None and baseline is not None and baseline > 0 else None


def answers(value):
    if isinstance(value, dict):
        if isinstance(value.get("moves"), list):
            if value["moves"] or value.get("depth") == 0 or value.get("cost") == 0 or value.get("optimal"):
                yield value
        for key, item in value.items():
            if key not in {"images", "request", "request_id", "config", "memory"}:
                yield from answers(item)
    elif isinstance(value, list):
        for item in value:
            yield from answers(item)


def delivered_answers(snapshot):
    for answer in (snapshot, snapshot.get("candidate_result"), snapshot.get("result")):
        if isinstance(answer, dict) and isinstance(answer.get("moves"), list):
            if answer["moves"] or answer.get("depth") == 0 or answer.get("cost") == 0:
                yield answer


def curve_cost(moves, metric):
    try:
        return solution_cost(moves, metric)
    except (TypeError, ValueError, KeyError):
        # Invalid formulas remain in the raw curve and validation_errors; they
        # must not abort serialization of the complete failed matrix summary.
        return None


def validate_formula(answer, facelets, metric, expected):
    assert answer.get("metric", metric) == metric, "formula metric does not match the request"
    state = from_facelets(facelets)
    moves = tuple(answer["moves"])
    for move in moves:
        state = state.apply_move_index(MOVE_INDEX[move])
    cost = solution_cost(moves, metric)
    assert state.is_solved(), f"invalid formula: {moves}"
    for field in ("cost", "depth"):
        if answer.get(field) is not None:
            assert type(answer[field]) is int and answer[field] == cost, f"incorrect reported {field}"
    if expected is not None:
        assert cost >= expected, "candidate shorter than the independently known optimum"
        if answer.get("optimal"):
            assert cost == expected, "incorrect known optimum"
    return {"moves": list(moves), "cost": cost, "solved": True, "optimal_claim": bool(answer.get("optimal"))}


def curves(case, terminal):
    generated, published, sent, delivered = [], [], [], []
    seen = set()
    snapshots = [frame.get("data", {}) for frame in case.get("events", [])] + [terminal]
    for snapshot in snapshots:
        for event in snapshot.get("timing_events", []):
            kind, seconds, cost = event.get("event"), finite(event.get("elapsed_seconds")), event.get("cost")
            if kind not in {"candidate_generated", "candidate_published", "native_incumbent_sent"}:
                continue
            key = (kind, seconds, cost, tuple(event.get("moves", [])))
            if key in seen:
                continue
            seen.add(key)
            item = {"seconds": seconds, "cost": cost, "moves": event.get("moves"), "source": kind}
            {"candidate_generated": generated, "candidate_published": published,
             "native_incumbent_sent": sent}[kind].append(item)
        for frame in snapshot.get("events", []):
            event = frame.get("event", {})
            if event.get("type") != "candidate":
                continue
            seconds, moves = finite(frame.get("request_seconds")), event.get("moves", [])
            cost = curve_cost(moves, case["metric"])
            key = ("qtm_candidate", seconds, cost, tuple(moves))
            if key in seen:
                continue
            seen.add(key)
            item = {"seconds": seconds, "cost": cost, "moves": moves,
                    "source": "qtm_candidate_received_and_published"}
            generated.append(dict(item))
            published.append(dict(item))
    for frame in case.get("events", []):
        for answer in delivered_answers(frame.get("data", {})):
            delivered.append({"seconds": finite(frame.get("seconds")),
                              "cost": curve_cost(answer["moves"], case["metric"]),
                              "moves": answer["moves"], "source": "normal_page_response"})
    for items in (generated, published, sent, delivered):
        items.sort(key=lambda item: item["seconds"] if item["seconds"] is not None else math.inf)
    return {"generated": generated, "published": published, "native_incumbent_sent": sent,
            "page_response_deliveries": delivered,
            "qtm_generation_scope": "Python receipt of native candidate; not native internal discovery time"}


def proof_bounds(terminal, result, candidate_cost):
    """Use completed layers and reported legal bounds, never an active layer."""
    progress = terminal.get("progress") or {}
    sources = (("terminal", terminal), ("result", result), ("progress", progress))
    completed = next(((value["completed_depth"], name) for name, value in sources
                      if type(value.get("completed_depth")) is int and value["completed_depth"] >= -1), None)
    lower_bounds = [(value[field], f"{name}.{field}") for name, value in sources
                    for field in ("proven_lower_bound", "lower_bound")
                    if type(value.get(field)) is int and value[field] >= 0]
    if completed is not None:
        lower_bounds.append((completed[0] + 1, f"{completed[1]}.completed_depth + 1"))
    lower = max(lower_bounds, key=lambda item: item[0]) if lower_bounds else None
    return {"completed_depth": completed[0] if completed else None,
            "completed_depth_source": completed[1] if completed else None,
            "proven_lower_bound": lower[0] if lower else None,
            "proven_lower_bound_source": lower[1] if lower else None,
            "proof_gap": candidate_cost - lower[0] if candidate_cost is not None and lower else None}


def summarize(report):
    frozen = {case["name"]: case for case in json.loads(
        (ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
    records, validation_errors = [], []
    for case in report["cases"]:
        metric, name = case["metric"], case["name"]
        errors, replays = [], []
        expected = (frozen[name].get("known_optimal_costs") or {}).get(metric)
        if case["facelets"] != frozen[name]["facelets"]:
            errors.append("request used a different Facelets state from the frozen reference")
        if hashlib.sha256(case["facelets"].encode()).hexdigest() != case.get("faceletsSha256"):
            errors.append("Facelets identity mismatch")
        # Validate every occurrence. A repeated formula with a wrong cost or
        # optimality claim must not escape through output deduplication.
        for answer in answers({"events": case.get("events", []), "final": case.get("final"),
                               "cleanup": case.get("afterCleanup")}):
            try:
                replays.append(validate_formula(answer, case["facelets"], metric, expected))
            except (AssertionError, KeyError, TypeError, ValueError) as error:
                errors.append(str(error))
        terminal = case.get("afterCleanup") or case.get("final") or {}
        result = terminal.get("result") or terminal
        status = terminal.get("status") or terminal.get("proof_status")
        optimal = result.get("optimal") is True and terminal.get("optimal", True) is not False and status == "complete"
        elapsed, source = finite(terminal.get("strict_confirmed_seconds")), None
        if elapsed is not None:
            source = "strict_confirmed_seconds"
        if elapsed is None:
            elapsed = next((finite(event.get("elapsed_seconds")) for event in terminal.get("timing_events", [])
                            if event.get("event") == "terminal"), None)
            source = "request_relative_terminal_event" if elapsed is not None else None
        if elapsed is None:
            elapsed = finite(terminal.get("terminal_seconds"))
            source = "terminal_seconds" if elapsed is not None else None
        # Never substitute native elapsed, resource hold or UI polling time.
        if optimal and elapsed is None:
            errors.append("strict result has no request-entry-relative terminal measurement")
        if optimal and not any(replay["optimal_claim"] for replay in replays):
            errors.append("strict result did not contain a verified optimal formula")
        memory = case.get("memory") or {}
        native_peak = finite(memory.get("native_process_lifetime_peak_bytes"))
        tree_peak = finite(memory.get("tree_sampled_peak_working_set_bytes"))
        memory_valid = memory.get("scope") == MEMORY_SCOPE and native_peak is not None and native_peak > 0
        candidate_curve = curves(case, terminal)
        first_delivery = next((item["seconds"] for item in candidate_curve["page_response_deliveries"]
                               if item["seconds"] is not None), None)
        first_generated = min((item["seconds"] for item in candidate_curve["generated"]
                               if item["seconds"] is not None), default=None)
        first_published = min((item["seconds"] for item in candidate_curve["published"]
                               if item["seconds"] is not None), default=None)
        if first_generated is None:
            first_generated = finite(terminal.get("first_candidate_generated_seconds",
                                                       terminal.get("first_candidate_seconds")))
        candidate_cost = min((r["cost"] for r in replays), default=None)
        bounds = proof_bounds(terminal, result, candidate_cost)
        if bounds["proof_gap"] is not None and bounds["proof_gap"] < 0:
            errors.append("reported proven lower bound exceeds a verified solution cost")
        success = optimal and elapsed is not None and elapsed <= 30 and not case.get("failure") and not errors
        records.append({"name": name, "metric": metric, "label": case["label"], "repeat": case["repeat"],
                        "status": status, "strict_success": success, "strict_seconds": elapsed,
                        "strict_time_source": source, "par2_seconds": elapsed if success else 60,
                        "first_delivery_seconds": first_delivery, "first_generated_seconds": first_generated,
                        "first_published_seconds": first_published,
                        "publication_wait_seconds": first_published - first_generated
                        if first_published is not None and first_generated is not None else None,
                        "candidate_curves": candidate_curve, "page_seconds": case.get("pageWallSeconds"),
                        "page_observation_delay_seconds": case["pageWallSeconds"] - elapsed
                        if case.get("pageWallSeconds") is not None and elapsed is not None else None,
                        "candidate_cost": candidate_cost, **bounds,
                        "native_peak_working_set_bytes": native_peak, "tree_sampled_peak_working_set_bytes": tree_peak,
                        "memory_comparable": memory_valid, "memory_scope": memory.get("scope"),
                        "validation_errors": errors, "replays": replays})
        if errors:
            validation_errors.append({"name": name, "metric": metric, "label": case["label"],
                                      "repeat": case["repeat"], "errors": errors})
    expected_keys = {(name, metric, label, repeat) for name in STATES for metric in METRICS
                     for label in LABELS for repeat in range(3)}
    keys = [(r["name"], r["metric"], r["label"], r["repeat"]) for r in records]
    complete = set(keys) == expected_keys and len(keys) == 72
    case_order = report.get("config", {}).get("caseOrder") or list(STATES)
    metric_order = report.get("config", {}).get("metrics") or list(METRICS)
    expected_order = [(name, metric, label, repeat) for repeat, labels in enumerate(
        (("baseline", "current"), ("current", "baseline"), ("baseline", "current")))
        for name in case_order for metric in metric_order for label in labels]
    order_valid = keys == expected_order
    fresh = all(case.get("newProcess") is True and case.get("processTreeStopped") is True
                and case.get("solveRequests") == 1 for case in report["cases"])
    summary = {}
    for metric in METRICS:
        selected = [r for r in records if r["metric"] == metric]
        if not selected:
            continue
        par2 = {label: statistics.mean(r["par2_seconds"] for r in selected if r["label"] == label)
                if any(r["label"] == label for r in selected) else None for label in LABELS}
        per_state, matched_ratios = {}, []
        for name in dict.fromkeys(r["name"] for r in selected):
            group = [r for r in selected if r["name"] == name]
            by_key = {(r["label"], r["repeat"]): r for r in group}
            pairs = [(by_key[("baseline", repeat)], by_key[("current", repeat)]) for repeat in range(3)
                     if ("baseline", repeat) in by_key and ("current", repeat) in by_key]
            completed_pairs = [(old, new) for old, new in pairs if old["strict_success"] and new["strict_success"]]
            medians = {label: median(r["strict_seconds"] for pair in completed_pairs for r in pair
                                    if r["label"] == label) for label in LABELS}
            strict_ratio = ratio(medians["current"], medians["baseline"])
            if strict_ratio is not None:
                matched_ratios.append(strict_ratio)
            paired_ratios = [ratio(new["strict_seconds"], old["strict_seconds"]) for old, new in completed_pairs]
            new_timeouts = [new["repeat"] for old, new in pairs if old["strict_success"] and not new["strict_success"]]
            reproducible = (strict_ratio is not None and strict_ratio > 1.05
                            and sum(value is not None and value > 1.05 for value in paired_ratios) >= 2)
            deliveries = {label: median(r["first_delivery_seconds"] for r in group if r["label"] == label)
                          for label in LABELS}
            delivery_ratio = ratio(deliveries["current"], deliveries["baseline"])
            waiting = any(old["publication_wait_seconds"] is not None and old["publication_wait_seconds"] > 0
                          for old, _ in pairs)
            resource = {}
            for field in ("native_peak_working_set_bytes", "tree_sampled_peak_working_set_bytes"):
                values = {label: median(r[field] for r in group if r["label"] == label and r["memory_comparable"])
                          for label in LABELS}
                resource[field] = {"medians": values, "current_over_baseline": ratio(values["current"], values["baseline"])}
            memory_ratio = resource["native_peak_working_set_bytes"]["current_over_baseline"]
            per_state[name] = {"strict_medians_of_same_repeat_completed_pairs": medians,
                "strict_current_over_baseline": strict_ratio, "completed_pair_ratios": paired_ratios,
                "new_timeout": bool(new_timeouts), "new_timeout_repeats": new_timeouts,
                "reproducible_strict_regression_over_5pct": reproducible,
                "strict_median_regression_over_5pct": strict_ratio is not None and strict_ratio > 1.05,
                "first_delivery_medians": deliveries, "first_delivery_current_over_baseline": delivery_ratio,
                "baseline_publication_wait_observed": waiting,
                "delivery_target_20pct_met": delivery_ratio <= 0.8 if delivery_ratio is not None and waiting else None,
                "resources": resource, "resource_median_growth_within_5pct": memory_ratio is not None and memory_ratio <= 1.05,
                "all_runs": group}
        peak_values = {label: max((r["native_peak_working_set_bytes"] for r in selected
                                  if r["label"] == label and r["memory_comparable"]), default=None) for label in LABELS}
        peak_ratio, par2_ratio = ratio(peak_values["current"], peak_values["baseline"]), ratio(par2["current"], par2["baseline"])
        states = list(per_state.values())
        delivery_targets = [state["delivery_target_20pct_met"] for state in states
                            if state["delivery_target_20pct_met"] is not None]
        summary[metric] = {"par2_mean_seconds": par2, "par2_current_over_baseline": par2_ratio,
            "per_state": per_state,
            "completed_geometric_mean_ratio": math.exp(statistics.mean(math.log(r) for r in matched_ratios))
                if matched_ratios else None,
            "target_met": par2_ratio is not None and par2_ratio <= 0.85,
            "no_new_timeout": not any(state["new_timeout"] for state in states),
            "no_reproducible_state_regression_over_5pct": not any(state["reproducible_strict_regression_over_5pct"] for state in states),
            "no_state_strict_median_regression_over_5pct": not any(state["strict_median_regression_over_5pct"] for state in states),
            "native_peak_bytes": peak_values, "native_peak_current_over_baseline": peak_ratio,
            "all_memory_samples_comparable": all(r["memory_comparable"] for r in selected),
            "resource_growth_within_5pct": peak_ratio is not None and peak_ratio <= 1.05
                and all(r["memory_comparable"] for r in selected)
                and all(state["resource_median_growth_within_5pct"] for state in states),
            "delivery_target_20pct_met_on_waiting_states": all(delivery_targets) if delivery_targets else None}
        summary[metric]["adoption_gates_met"] = (complete and order_valid and fresh
            and not report.get("failures") and not validation_errors
            and summary[metric]["target_met"] and summary[metric]["no_new_timeout"]
            and summary[metric]["no_reproducible_state_regression_over_5pct"]
            and summary[metric]["resource_growth_within_5pct"])
    return {"matrix_complete": complete, "fixed_pair_order_valid": order_valid, "all_requests_fresh": fresh,
            "expected_runs": 72, "actual_runs": len(records),
            "package_identity": report.get("packageIdentity"), "matrix_config": report.get("config"),
            "matrix_config_sha256": report.get("configSha256"),
            "harness_source_sha256": report.get("harnessSourceSha256"), "harness_runtime": report.get("harnessRuntime"),
            "persistence_scope": report.get("persistenceScope"),
            "missing_runs": sorted(expected_keys - set(keys)), "duplicate_runs": len(keys) - len(set(keys)),
            "records": records, "summary": summary, "validation_errors": validation_errors,
            "failures": report.get("failures", []), "memory_scope": MEMORY_SCOPE,
            "scope": "fixed six-state regression set; all timeouts penalized at 60 seconds; missing strict time is never inferred"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    opener = gzip.open if args.input.suffix == ".gz" else open
    with opener(args.input, "rt", encoding="utf-8") as source:
        report = summarize(json.load(source))
    with args.input.open("rb") as source:
        input_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    report["analysis"] = {
        "input": str(args.input.resolve()), "input_sha256": input_sha256,
        "parser_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "bounds_scope": "reported legal lower bounds and completed layers; active layers never imply proof",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: {k: v for k, v in value.items() if k != "per_state"}
                      for key, value in report["summary"].items()}, indent=2))
    if (not report["matrix_complete"] or not report["fixed_pair_order_valid"] or not report["all_requests_fresh"]
            or report["validation_errors"] or report["failures"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
