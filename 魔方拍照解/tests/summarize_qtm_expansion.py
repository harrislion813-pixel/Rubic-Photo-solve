"""Pair all frozen proof-expansion cases, retaining timeouts as censored runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data["metric"] != "QTM" or data["incumbent_mode"] != "fixed" or
            data["proof_cache_reuse"] or data["repeats"] != 3 or
            data["timeout_seconds"] != 60 or data["threads"] != "4" or
            data["variants"] != ["staged"] or len(data["runs"]) != 120):
        raise AssertionError(f"incorrect expansion protocol: {path}")
    names = {case["name"] for case in data["selected_cases"]}
    if len(names) != 40 or len({(row["case"], row["repeat"]) for row in data["runs"]}) != 120:
        raise AssertionError(f"missing or duplicated expansion case: {path}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("strong", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    baseline = load(args.baseline)
    strong = load(args.strong)
    if (baseline["cases_file"]["sha256"] != strong["cases_file"]["sha256"] or
            baseline["native_flags"] or strong["native_flags"] != ["--no-native-candidate"]):
        raise AssertionError("expansion cases or native candidate conditions differ")
    old = {(row["case"], row["repeat"]): row for row in baseline["runs"]}
    new = {(row["case"], row["repeat"]): row for row in strong["runs"]}
    if set(old) != set(new):
        raise AssertionError("expansion run keys differ")
    rows = []
    for name in sorted({name for name, _ in old}):
        old_three = [old[(name, repeat)] for repeat in range(3)]
        new_three = [new[(name, repeat)] for repeat in range(3)]
        old_ok = sum(bool(row["result"].get("optimal")) for row in old_three)
        new_ok = sum(bool(row["result"].get("optimal")) for row in new_three)
        old_median = statistics.median(row["wall_seconds"] for row in old_three)
        new_median = statistics.median(row["wall_seconds"] for row in new_three)
        eligible = old_ok == new_ok == 3 and old_median >= 0.1
        same_completed_depth = all(old[(name, repeat)]["completed_depth"] ==
                                   new[(name, repeat)]["completed_depth"] for repeat in range(3))
        old_generated = statistics.median(row["result"]["generated_candidates"] for row in old_three)
        new_generated = statistics.median(row["result"]["generated_candidates"] for row in new_three)
        generated_ratio = (old_generated / new_generated if eligible and same_completed_depth and
                           old_generated > 0 and new_generated > 0 else None)
        rows.append({"case": name, "baseline_completed": old_ok, "strong_completed": new_ok,
                     "baseline_median_wall_seconds": old_median,
                     "strong_median_wall_seconds": new_median,
                     "paired_speedup": old_median / new_median if eligible else None,
                     "same_completed_depth": same_completed_depth,
                     "baseline_median_generated": old_generated,
                     "strong_median_generated": new_generated,
                     "generated_ratio": generated_ratio})
    ratios = [row["paired_speedup"] for row in rows if row["paired_speedup"] is not None]
    generated_ratios = [row["generated_ratio"] for row in rows if row["generated_ratio"] is not None]
    output = {"schema_version": 1, "metric": "QTM", "timeout_seconds": 60,
              "baseline_raw": {"path": str(args.baseline), "sha256": sha256(args.baseline)},
              "strong_raw": {"path": str(args.strong), "sha256": sha256(args.strong)},
              "cases_file_sha256": baseline["cases_file"]["sha256"],
              "eligible_cases": len(ratios),
              "geometric_mean_paired_speedup": math.exp(statistics.mean(map(math.log, ratios))) if ratios else None,
              "same_completed_depth_generated_cases": len(generated_ratios),
              "geometric_mean_generated_reduction": math.exp(statistics.mean(map(math.log, generated_ratios)))
              if generated_ratios else None,
              "cases": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"eligible_cases": output["eligible_cases"],
                      "geometric_mean_paired_speedup": output["geometric_mean_paired_speedup"],
                      "geometric_mean_generated_reduction": output["geometric_mean_generated_reduction"]}))


if __name__ == "__main__":
    main()
