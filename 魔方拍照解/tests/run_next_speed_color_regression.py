"""Replay web color classification from lossless actual browser Canvas evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/benchmarks/next-speed-2026-10-02"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-report", type=Path, default=EVIDENCE / "photo-recognition.json")
    parser.add_argument("--output", type=Path, default=EVIDENCE / "browser-patch-color-regression.json")
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    browser_report = json.loads(args.browser_report.read_text(encoding="utf-8"))
    assert browser_report["passed"] and browser_report["solveRequests"] == 0
    report = {"method": "Lossless PNG pixels captured from actual browser Canvas, exact 71x71 sticker patches and center ring; no resizing, re-encoding or re-detection. Expected labels from independent frozen human reference.",
              "browser_report_sha256": hashlib.sha256(args.browser_report.read_bytes()).hexdigest(),
              "cases": []}
    frozen = {case["name"]: case for case in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
    for case in browser_report["cases"]:
        group = case["name"].split("-")[1]
        extracted = subprocess.run([sys.executable, str(ROOT / "tests/extract_real_patches.py"), "--group", group,
                                    "--browser-report", str(args.browser_report)], capture_output=True, text=True, encoding="utf-8", check=True)
        # Pixel-level red/orange prototype separability is a separate diagnostic
        # for the historical OpenCV pipeline. Here verify all actual Canvas labels
        # and quality directly; balanced classification can correct an uncertain
        # sticker whose closest single prototype has the wrong color.
        tested = subprocess.run([args.node, str(ROOT / "tests/classify_real_case.mjs")],
                                input=extracted.stdout, capture_output=True, text=True, encoding="utf-8")
        classified = json.loads(tested.stdout) if tested.returncode == 0 else None
        matches = classified is not None and classified["labels"] == frozen[case["name"]]["faces"]
        result = {"name": case["name"], "returncode": tested.returncode, "stdout": tested.stdout, "stderr": tested.stderr,
                  "matches_reference": matches, "quality_valid": classified is not None and classified["quality"]["valid"],
                  "preview_sha256": {face: hashlib.sha256((args.browser_report.parent / relative).read_bytes()).hexdigest()
                                     for face, relative in case["previewPaths"].items()}}
        report["cases"].append(result)
        print(f"{case['name']}: actual browser patch color regression exit={tested.returncode}")
    report["passed"] = all(case["returncode"] == 0 and case["matches_reference"] and case["quality_valid"] for case in report["cases"])
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit("actual browser patch color regression failed; all attempts retained")


if __name__ == "__main__":
    main()
