"""Start the frozen Windows app and verify four HTM/QTM solves over HTTP."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost
from cube_app.two_by_two import is_solved_2x2, to_facelets_2x2


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--missing-strong", action="store_true",
                        help="temporarily hide the strong PDB and verify safe profile degradation")
    args = parser.parse_args()
    package = args.package.resolve()
    executable = package / "RubicPhotoSolve.exe"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    strong_asset = package / ".cache/native/strong_qtm_v3.pdb"
    hidden_asset = package / ".cache/native/strong_qtm_v3.pdb.verification-hidden"
    if args.missing_strong:
        if hidden_asset.exists() or not strong_asset.is_file():
            raise FileNotFoundError("strong asset cannot be hidden safely")
        strong_asset.rename(hidden_asset)
    process = None
    try:
        port_file = package / ".cache/server_port.txt"
        old_mtime = port_file.stat().st_mtime_ns if port_file.exists() else -1
        process = subprocess.Popen([str(executable)], cwd=package,
                                   env={**os.environ, "CUBE_NO_BROWSER": "1"},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"frozen application exited: {process.returncode}")
            if port_file.is_file() and port_file.stat().st_mtime_ns != old_mtime:
                base = port_file.read_text(encoding="utf-8").strip()
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("frozen application did not write its port file")

        def get(path: str) -> dict:
            with urllib.request.urlopen(base.rstrip("/") + path, timeout=30) as response:
                return json.load(response)

        def post(path: str, payload: dict) -> dict:
            request = urllib.request.Request(base.rstrip("/") + path,
                                             data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)

        version = get("/api/version")
        if not version.get("ok"):
            raise AssertionError(version)

        def solve(cube: CubieCube, metric: str, size: int, maximum: int) -> dict:
            facelets = to_facelets_2x2(cube) if size == 2 else to_facelets(cube)
            response = post("/api/solve", {"facelets": facelets, "cube_size": size,
                                           "metric": metric, "max_depth": maximum,
                                           "timeout_seconds": 20})
            job_id = response.get("job_id")
            until = time.monotonic() + 30
            while job_id and response.get("proof_status") not in {"complete", "budget_exhausted", "timeout", "error"}:
                if time.monotonic() >= until:
                    raise TimeoutError(f"frozen {size}x{size} {metric} solve timed out")
                time.sleep(0.05)
                job = get("/api/solve/" + job_id)
                response = {"proof_status": job["status"], **(job.get("result") or {})}
            if response.get("proof_status") != "complete" or not response.get("optimal"):
                raise AssertionError(response)
            verified = cube
            for move in response["moves"]:
                verified = verified.apply_move_index(MOVE_INDEX[move])
            if (not (is_solved_2x2(verified) if size == 2 else verified.is_solved()) or
                    solution_cost(response["moves"], metric) != response["depth"]):
                raise AssertionError(f"invalid frozen {size}x{size} {metric} solve")
            return response

        half = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        two_htm = solve(half, "HTM", 2, 11)
        two_qtm = solve(half, "QTM", 2, 14)
        three_htm = solve(half, "HTM", 3, 2)
        oracle = json.loads((ROOT / "tests/qtm_acceptance_cases.json").read_text(encoding="utf-8"))[0]
        from cube_app.cubie import from_facelets
        oracle_depth = oracle["expected_qtm_depth"]
        three_qtm = solve(from_facelets(oracle["facelets"]), "QTM", 3, oracle_depth)
        depths = [two_htm["depth"], two_qtm["depth"], three_htm["depth"], three_qtm["depth"]]
        if depths != [1, 2, 1, oracle_depth]:
            raise AssertionError(depths)
        qtm_profile = three_qtm.get("asset_profile")
        if args.missing_strong and qtm_profile == "strong":
            raise AssertionError("frozen application advertised strong despite its missing PDB")
        if not args.missing_strong and qtm_profile != "strong":
            raise AssertionError(f"frozen application did not load strong assets: {qtm_profile}")
        superflip = CubieCube(eo=(1,) * 12)
        pending = post("/api/solve", {"facelets": to_facelets(superflip), "cube_size": 3,
                                      "metric": "QTM", "timeout_seconds": 20})
        if not pending.get("job_id"):
            raise AssertionError(f"frozen cancellation probe did not start a job: {pending}")
        cancelled = post("/api/solve/" + pending["job_id"] + "/cancel", {})
        if cancelled.get("status") != "cancelled":
            raise AssertionError(f"frozen cancellation failed: {cancelled}")
        second_oracle = json.loads((ROOT / "tests/qtm_acceptance_cases.json").read_text(encoding="utf-8"))[1]
        after_cancel = solve(from_facelets(second_oracle["facelets"]), "QTM", 3,
                             second_oracle["expected_qtm_depth"])
        print(json.dumps({"ok": True, "version": version.get("version"),
                          "depths_2x2_htm_qtm_3x3_htm_qtm": depths,
                          "qtm_asset_profile": qtm_profile,
                          "cancel_status": cancelled["status"],
                          "after_cancel_qtm_depth": after_cancel["depth"]}))
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if args.missing_strong and hidden_asset.exists():
            hidden_asset.rename(strong_asset)


if __name__ == "__main__":
    main()
