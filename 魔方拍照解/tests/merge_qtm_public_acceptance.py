"""Combine immutable 45-case runs with separately measured public hard cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmark_native import case_state, file_metadata
from cube_app.cubie import to_facelets


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("public", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cases-file", type=Path, default=ROOT / "tests/qtm_acceptance_public_cases.json")
    args = parser.parse_args()
    old = json.loads(args.original.read_text(encoding="utf-8"))
    new = json.loads(args.public.read_text(encoding="utf-8"))
    cases = json.loads(args.cases_file.read_text(encoding="utf-8"))
    names = [case["name"] for case in cases]
    if len(names) != 48 or len(set(names)) != 48 or len(new["selected_cases"]) != 3:
        raise AssertionError("public acceptance cases must be 45 old plus 3 published positions")
    public_names = {case["name"] for case in new["selected_cases"]}
    if public_names != {"superflip-fourspot", "antipode-neighbor-a", "antipode-neighbor-b"}:
        raise AssertionError("unexpected public pressure cases")
    retained = set(names) - public_names
    if len(retained) != 45 or len(old["runs"]) != 144 or len(new["runs"]) != 9:
        raise AssertionError("source benchmark runs are incomplete")
    for key in ("metric", "profile", "incumbent_mode", "native_flags",
                "proof_cache_reuse", "binary", "pdbs", "pdb_manifest"):
        if old.get(key) != new.get(key):
            raise AssertionError(f"source benchmark protocol differs: {key}")
    for source in (old, new):
        if (set(row["threads"] for row in source["runs"]) != {4} or
                set(row["repeat"] for row in source["runs"]) != {0, 1, 2} or
                set(row["variant"] for row in source["runs"]) != {"staged"}):
            raise AssertionError("source run-level threads, repeats or variants differ")
    if old.get("timeout_seconds", 60) != 60 or new.get("timeout_seconds", 60) != 60:
        raise AssertionError("source runs are not 60-second acceptance runs")
    by_key = {(run["case"], run["repeat"]): run for run in old["runs"] if run["case"] in retained}
    by_key.update({(run["case"], run["repeat"]): run for run in new["runs"]})
    if len(by_key) != 144 or set(by_key) != {(name, repeat) for name in names for repeat in range(3)}:
        raise AssertionError("merged benchmark has missing or duplicate cases")
    output = {key: value for key, value in old.items() if key not in
              {"cases_file", "selected_cases", "cold_starts", "runs", "summaries"}}
    output["schema_version"] = 2
    output["timeout_seconds"] = 60
    output["threads"] = "4"
    output["repeats"] = 3
    output["variants"] = ["staged"]
    output["cases_file"] = file_metadata(args.cases_file)
    output["selected_cases"] = [
        {"name": case["name"], "facelets": to_facelets(case_state(case)[0]),
         "incumbent": case_state(case)[1]} for case in cases
    ]
    output["cold_starts"] = old["cold_starts"] + new["cold_starts"]
    output["runs"] = [by_key[(name, repeat)] for repeat in range(3) for name in names]
    output["source_raw"] = [
        {"path": str(path), "sha256": sha256(path)} for path in (args.original, args.public)
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(output["runs"]), "cases": len(names),
                      "source_sha256": [row["sha256"] for row in output["source_raw"]]}))


if __name__ == "__main__":
    main()
