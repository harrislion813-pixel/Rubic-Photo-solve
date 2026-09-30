"""Check optional QTM absence and HTM 2x2 on the unpacked HtmFull release."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from accept_isolated_package import request, start
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.solvers.htm.two_by_two import to_facelets_2x2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    process, base, lines = start(args.package.resolve(), "eager")
    output = {"package": str(args.package.resolve())}
    try:
        output["capabilities"] = request(base + "/api/capabilities")
        cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        output["qtm_missing"] = request(base + "/api/solve", {
            "facelets": to_facelets(cube), "cube_size": 3, "metric": "QTM",
            "max_depth": 2, "timeout_seconds": 5,
        })
        output["qtm_missing_job"] = request(base + "/api/solve/qtm-absent")
        output["qtm_missing_cancel"] = request(base + "/api/solve/qtm-absent/cancel", {})
        output["htm_two_by_two"] = request(base + "/api/solve", {
            "facelets": to_facelets_2x2(cube), "cube_size": 2, "metric": "HTM",
            "max_depth": 1, "timeout_seconds": 5,
        })
        first = request(base + "/api/solve", {
            "facelets": to_facelets(cube), "cube_size": 3, "metric": "HTM",
            "max_depth": 1, "timeout_seconds": 5,
        })
        output["htm_three_by_three_initial"] = first
        final = first
        until = time.monotonic() + 5
        while final.get("job_id") and final.get("status", final.get("proof_status")) != "complete":
            if time.monotonic() >= until:
                raise TimeoutError("HTM shallow package solve did not finish")
            time.sleep(0.1)
            final = request(base + "/api/solve/" + first["job_id"])
        output["htm_three_by_three_final"] = final
        if output["capabilities"].get("QTM") is not False:
            raise AssertionError("HtmFull advertised QTM")
        if (output["qtm_missing"].get("http_status") != 503
                or output["qtm_missing_job"].get("http_status") != 404
                or output["qtm_missing_cancel"].get("http_status") != 404):
            raise AssertionError("HtmFull did not reject absent QTM cleanly")
        if (output["htm_two_by_two"].get("depth") != 1
                or output["htm_two_by_two"].get("proof_status") != "complete"):
            raise AssertionError("HTM 2x2 package result is wrong")
        solved = final.get("result") or final
        if solved.get("depth") != 1 or not solved.get("optimal"):
            raise AssertionError("HTM 3x3 was affected by missing QTM")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output["server_log"] = lines
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"qtm_missing_status": output["qtm_missing"].get("http_status"),
                      "htm_2x2_depth": output["htm_two_by_two"].get("depth")}))


if __name__ == "__main__":
    main()
