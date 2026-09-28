"""Summarize frozen HTM regression and equal-depth QTM kernel ablations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / ".cache"


def load(name: str) -> tuple[dict, dict]:
    path = RAW / name
    data = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return data, {"path": str(path.relative_to(ROOT)), "sha256": digest}


def row_summary(rows: list[dict]) -> dict:
    if len({row["completed_depth"] for row in rows}) != 1:
        raise AssertionError("runs reached different completed depths")
    return {"runs": len(rows), "completed_depth": rows[0]["completed_depth"],
            "optimal_proofs": sum(bool(row["result"].get("optimal")) for row in rows),
            "median_wall_seconds": statistics.median(row["wall_seconds"] for row in rows),
            "median_generated_candidates": statistics.median(row["result"]["generated_candidates"]
                                                            for row in rows),
            "median_transposition_hits": statistics.median(row["result"]["transposition_hits"]
                                                            for row in rows)}


def main() -> None:
    output: dict = {"schema_version": 1, "htm_regression": {}, "qtm_pgo16_equal_depth": {}}
    htm_data = {}
    for name, filename in (("baseline", "qtm-htm-regression-b0-4x3x2.json"),
                           ("strong_binary", "qtm-htm-regression-current-4x3x2.json")):
        data, source = load(filename)
        if (data["metric"] != "HTM" or data["threads"] != "4" or data["repeats"] != 3 or
                data["timeout_seconds"] != 2 or len(data["runs"]) != 12):
            raise AssertionError(f"incorrect HTM regression protocol: {filename}")
        htm_data[name] = data
        output["htm_regression"][name] = {"source": source, "cases": {
            case: row_summary([row for row in data["runs"] if row["case"] == case])
            for case in sorted({row["case"] for row in data["runs"]})}}
    if htm_data["baseline"]["cases_file"]["sha256"] != htm_data["strong_binary"]["cases_file"]["sha256"]:
        raise AssertionError("HTM cases differ")
    output["htm_regression"]["median_wall_ratio_new_over_old"] = {
        case: (output["htm_regression"]["strong_binary"]["cases"][case]["median_wall_seconds"] /
               output["htm_regression"]["baseline"]["cases"][case]["median_wall_seconds"])
        for case in output["htm_regression"]["baseline"]["cases"]}

    for name, filename in (
        ("strong_no_tail", "qtm-ablation-strong-no-tail-pgo16-3x2.json"),
        ("strong_tail7", "qtm-ablation-strong-tail7-pgo16-3x2.json"),
        ("strong_tail8", "qtm-ablation-strong-tail8-pgo16-3x2.json"),
        ("transposition", "qtm-ablation-tt-pgo16-3x2.json"),
        ("no_direction_probe", "qtm-ablation-no-direction-pgo16-3x2.json"),
        ("thread_counts", "qtm-ablation-threads-pgo16-3x2.json"),
    ):
        data, source = load(filename)
        expected = 12 if name == "thread_counts" else 3
        if (data["metric"] != "QTM" or data["repeats"] != 3 or data["timeout_seconds"] != 2 or
                data["max_cost"] != 18 or data["native_flags"].count("--no-native-candidate") != 1 or
                len(data["runs"]) != expected or {row["case"] for row in data["runs"]} != {"pgo16"}):
            raise AssertionError(f"incorrect QTM ablation protocol: {filename}")
        groups = {str(threads): row_summary([row for row in data["runs"] if row["threads"] == threads])
                  for threads in sorted({row["threads"] for row in data["runs"]})}
        if any(group["runs"] != 3 or group["completed_depth"] != 18 for group in groups.values()):
            raise AssertionError(f"QTM ablation did not match depth 18: {filename}")
        output["qtm_pgo16_equal_depth"][name] = {"source": source, "profile": data["profile"],
                                                  "native_flags": data["native_flags"],
                                                  "by_threads": groups}
    path = ROOT / "docs/benchmarks/qtm-q6-ablations-2026-09-29.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"htm_wall_ratios": output["htm_regression"]["median_wall_ratio_new_over_old"],
                      "qtm_pgo16_medians": {
                          name: {threads: group["median_wall_seconds"]
                                 for threads, group in record["by_threads"].items()}
                          for name, record in output["qtm_pgo16_equal_depth"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
