"""Check that QTM starts on demand and its native process exits after a request."""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import time
from pathlib import Path

from accept_isolated_package import request, start
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets


def qtm_processes() -> list[dict]:
    output = subprocess.check_output(
        ["tasklist", "/FI", "IMAGENAME eq cube_solver_qtm.exe", "/FO", "CSV", "/NH"],
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return [{"image": row[0], "pid": row[1], "memory": row[4]}
            for row in csv.reader(io.StringIO(output))
            if len(row) >= 5 and row[0].lower() == "cube_solver_qtm.exe"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = qtm_processes()
    process, base, lines = start(args.package.resolve(), "eager")
    report = {"package": str(args.package.resolve()), "before": before}
    try:
        report["capabilities"] = request(base + "/api/capabilities")
        report["after_start"] = qtm_processes()
        if len(report["after_start"]) != len(before):
            raise AssertionError("QTM process was preheated on application startup")
        cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        first = request(base + "/api/solve", {
            "facelets": to_facelets(cube), "cube_size": 3, "metric": "QTM",
            "max_depth": 2, "timeout_seconds": 30,
        })
        report["initial"] = first
        final = first
        until = time.monotonic() + 30
        while first.get("job_id") and final.get("status", final.get("proof_status")) != "complete":
            if time.monotonic() >= until:
                raise TimeoutError("QTM shallow package solve exceeded 30 seconds")
            time.sleep(0.1)
            final = request(base + "/api/solve/" + first["job_id"])
        report["final_result"] = final
        result = final.get("result") or final
        if result.get("depth") != 2 or result.get("optimal") is not True:
            raise AssertionError("QTM package shallow result is not exact")
        until = time.monotonic() + 5
        while time.monotonic() < until and len(qtm_processes()) > len(before):
            time.sleep(0.1)
        report["after_request"] = qtm_processes()
        if len(report["after_request"]) != len(before):
            raise AssertionError("QTM native process remained after the request")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        report["server_log"] = lines
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"preheated": len(report["after_start"]) - len(before),
                      "remaining": len(report["after_request"]) - len(before)}))


if __name__ == "__main__":
    main()
