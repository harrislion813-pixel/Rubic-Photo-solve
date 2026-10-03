"""Validate the eight normal-page default-package checks without a speed claim."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from summarize_next_speed import summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    checked = summarize(raw)
    expected = {(name, metric, label, 0) for name in ("initial-1", "initial-12")
                for metric in ("HTM", "QTM") for label in ("baseline", "current")}
    keys = [(case["name"], case["metric"], case["label"], case["repeat"]) for case in raw["cases"]]
    assert len(keys) == 8 and set(keys) == expected
    assert not raw["formalMatrix"] and not checked["failures"] and not checked["validation_errors"]
    assert checked["all_requests_fresh"]
    defaults = []
    for case in raw["cases"]:
        assert case["referenceDifferences"] == [] and case["inputCorrection"]["changedStickers"] == 0
        assert case["inputCorrection"]["manuallyClickedStickers"] == 0 and case["pageErrors"] == []
        for view in ("desktop", "mobile"):
            layout = case[view]
            assert layout["documentWidth"] <= layout["viewport"]["width"] + 1
            assert not layout["overlaps"] and all(not box["clipped"] for box in layout["boxes"])
            assert len(layout["canvases"]) == 6 and all(c["sampledColors"] > 15 for c in layout["canvases"])
        if case["label"] != "current":
            continue
        snapshots = [frame["data"] for frame in case["events"]] + [case["afterCleanup"]]
        if case["metric"] == "HTM":
            assert case["afterCleanup"]["early_candidate_delivery"] is False
            assert all(snapshot.get("early_candidate_delivery", False) is False for snapshot in snapshots)
            events = case["afterCleanup"]["timing_events"]
            publications = [e for e in events if e["event"] == "candidate_published"]
            assert len(publications) == 1
            assert publications[0]["cost"] == case["afterCleanup"]["candidate_result"]["depth"]
            defaults.append({"name": case["name"], "metric": "HTM", "early_delivery": False,
                             "single_best_candidate_published": True})
        else:
            expansions = [(snapshot.get("progress") or {}).get("full_strong_expansions", 0)
                          for snapshot in snapshots]
            assert all(value == 0 for value in expansions)
            terminal = case["afterCleanup"]
            assert terminal["asset_profile"] == "strong"
            assert terminal["strong_adopted_seconds"] is not None and terminal["tail_adopted_seconds"] is not None
            defaults.append({"name": case["name"], "metric": "QTM", "full_strong_expansions": 0,
                             "asset_profile": terminal["asset_profile"], "strong_and_tail_adopted": True})
    report = {"scope": "eight functional requests only; no repeated speed or adoption decision",
              "input": str(args.input.resolve()), "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
              "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "summary_parser_sha256": hashlib.sha256(Path(__file__).with_name("summarize_next_speed.py").read_bytes()).hexdigest(),
              "actual_runs": 8, "all_requests_fresh": True, "default_configuration_checks": defaults,
              "formula_occurrences_replayed": sum(len(r["replays"]) for r in checked["records"]),
              "results": [{k: record[k] for k in ("name", "metric", "label", "status", "strict_success",
                          "candidate_cost", "completed_depth", "proven_lower_bound", "proof_gap")}
                          for record in checked["records"]],
              "package_identity": checked["package_identity"], "validation_errors": [], "failures": []}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("actual_runs", "formula_occurrences_replayed", "validation_errors", "failures")}))


if __name__ == "__main__":
    main()
