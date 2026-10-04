"""AB/BA/AB, six frozen photo states, fresh processes and 30-second HTTP deadlines."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--current-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-policy", default="six")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error("refusing to overwrite earlier evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    row_dir = args.output.parent / args.output.stem
    row_dir.mkdir(exist_ok=False)
    roots = {"baseline": args.baseline_root.resolve(), "current": args.current_root.resolve()}
    report = {"scope": "Real HTTP handler, fresh application and native processes, warm OS and disk caches; no external moves or proofs",
              "deadline_seconds": 30, "threads": 15, "candidate_threads": 1, "runs": [], "identity": {}}
    for label, root in roots.items():
        files = [root / "server.py", root / "native/htm/build/cube_solver_htm.exe"]
        files += sorted((root / "cube_app/solvers/htm").glob("*.py"))
        report["identity"][label] = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    cases = {c["name"]: c for c in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}

    def save():
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        for repeat, order in enumerate((("baseline", "current"), ("current", "baseline"), ("baseline", "current"))):
            for name in ("initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16"):
                for label in order:
                    output = row_dir / f"{repeat}-{name}-{label}.json"
                    environment = {k: v for k, v in os.environ.items() if not k.startswith("CUBE_")}
                    if label == "current":
                        environment["CUBE_HTM_NATIVE_CANDIDATE"] = args.candidate_policy
                    command = [sys.executable, "-X", "utf8", str(ROOT / "tests/htm_http_request_probe.py"),
                               "--root", str(roots[label]), "--facelets", cases[name]["facelets"], "--output", str(output)]
                    completed = subprocess.run(command, cwd=roots[label], env=environment, capture_output=True,
                                               text=True, encoding="utf-8", timeout=45,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if not output.exists():
                        report.setdefault("failures", []).append({"case": name, "label": label, "repeat": repeat,
                            "returncode": completed.returncode, "stderr": completed.stderr})
                        save()
                        raise RuntimeError(completed.stderr)
                    row = json.loads(output.read_text(encoding="utf-8"))
                    row.update(case=name, label=label, repeat=repeat, stderr=completed.stderr)
                    report["runs"].append(row)
                    save()
                    assert completed.returncode == 0, completed.stderr
                    terminal = row["terminal"]
                    print(json.dumps({"case": name, "label": label, "repeat": repeat, "status": terminal["status"],
                                      "seconds": row["wall_seconds"], "candidate": (terminal.get("candidate_result") or {}).get("depth")}), flush=True)
        report["summary"] = {}
        for label in roots:
            rows = [r for r in report["runs"] if r["label"] == label]
            report["summary"][label] = {"strict_successes": sum(r["terminal"]["status"] == "complete" and
                r["terminal"]["result"]["optimal"] for r in rows),
                "par2_seconds": statistics.mean(r["wall_seconds"] if r["terminal"]["status"] == "complete" else 60 for r in rows),
                "cases": {name: {"median_seconds": statistics.median(r["wall_seconds"] for r in rows if r["case"] == name),
                    "timeouts": sum(r["terminal"]["status"] != "complete" for r in rows if r["case"] == name)} for name in cases if name in
                    ("initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16")}}
        old, new = report["summary"]["baseline"], report["summary"]["current"]
        report["par2_improvement"] = 1 - new["par2_seconds"] / old["par2_seconds"]
        report["adopt"] = report["par2_improvement"] >= 0.15 and all(new["cases"][name]["timeouts"] <= old["cases"][name]["timeouts"]
                                                                 for name in new["cases"])
        print(json.dumps({"summary": report["summary"], "adopt": report["adopt"]}, indent=2), flush=True)
    finally:
        save()


if __name__ == "__main__":
    main()
