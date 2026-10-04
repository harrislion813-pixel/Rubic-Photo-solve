"""Verify fresh ZIP extraction, native asset use and replayed HTTP solutions."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "release"))
from cube_app import __version__  # noqa: E402
from cube_app.cubie import CubieCube, MOVE_INDEX, from_facelets, to_facelets  # noqa: E402
from cube_app.metrics import solution_cost  # noqa: E402
from cube_app.solvers.htm.two_by_two import is_solved_2x2, to_facelets_2x2  # noqa: E402
from verify_installation import verify  # noqa: E402
from package_release import inspect_portable  # noqa: E402


def request(base, endpoint, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(base + endpoint, data=data,
                  headers={} if body is None else {"Content-Type": "application/json"})
    with urlopen(req, timeout=45) as response:
        return json.load(response)


def run(root, command, qtm, expected_qtm_profile="strong", *, htm_photos=False):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("CUBE_") and k != "PYTHONPATH"}
    environment.update(CUBE_QTM_ASSET_PROFILE="strong", CUBE_QTM_STRONG_FORMAT="nibble",
                       CUBE_NATIVE_ASSET_LOADING="eager", CUBE_NO_BROWSER="1")
    port_file = root / ".cache/server_port.txt"
    port_file.unlink(missing_ok=True)
    result = {}
    with (root / "smoke.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=root, env=environment, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 30
            while not port_file.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"server failed to start: {root}")
                time.sleep(.1)
            base = port_file.read_text().strip().rstrip("/")
            assert request(base, "/api/version")["version"] == __version__
            with urlopen(base + "/", timeout=5) as page:
                html = page.read().decode("utf-8")
                assert page.headers["X-Cube-App-Version"] == __version__
            assert f'content="{__version__}"' in html and "__APP_VERSION__" not in html
            capabilities = request(base, "/api/capabilities")
            assert capabilities["QTM"] is qtm
            assert capabilities["QTM_status"] == ("stable" if qtm else "unavailable")
            result["capabilities"] = capabilities
            for metric in (("HTM", "QTM") if qtm else ("HTM",)):
                for size in (2, 3):
                    cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
                    response = request(base, "/api/solve",
                                       {"cube_size": size, "facelets": to_facelets_2x2(cube) if size == 2 else to_facelets(cube),
                                        "metric": metric, "timeout_seconds": 40})
                    until = time.monotonic() + 45
                    while response.get("proof_status") != "complete":
                        assert response.get("job_id") and time.monotonic() < until, response
                        job = request(base, "/api/solve/" + response["job_id"])
                        if job["status"] in {"error", "timeout", "cancelled", "budget_exhausted"}:
                            raise AssertionError(job)
                        response = {**response, **(job.get("result") or {}), "proof_status": job["status"]}
                        time.sleep(.1)
                    assert response["optimal"] and response["depth"] == (1 if metric == "HTM" else 2), response
                    for move in response["moves"]:
                        cube = cube.apply_move_index(MOVE_INDEX[move])
                    assert (is_solved_2x2(cube) if size == 2 else cube.is_solved())
                    assert solution_cost(response["moves"], metric) == response["depth"]
                    if metric == "QTM" and size == 3 and expected_qtm_profile is not None:
                        assert response.get("asset_profile") == expected_qtm_profile, response
                    result[f"{size}x{size}-{metric}"] = {"depth": response["depth"],
                        "optimal": response["optimal"], "asset_profile": response.get("asset_profile")}
            if htm_photos:
                cases = {case["name"]: case for case in json.loads(
                    (ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
                result["htm_photos"] = []
                for name, optimum in (("initial-1", 18), ("initial-12", 17)):
                    started = time.monotonic()
                    initial = request(base, "/api/solve", {"cube_size": 3,
                        "facelets": cases[name]["facelets"], "metric": "HTM",
                        "max_depth": 20, "timeout_seconds": 30})
                    assert initial.get("job_id"), initial
                    until = started + 35
                    while True:
                        job = request(base, "/api/solve/" + initial["job_id"])
                        if job["status"] == "complete":
                            break
                        assert job["status"] not in {"error", "timeout", "cancelled", "budget_exhausted"}, job
                        assert time.monotonic() < until, job
                        time.sleep(.1)
                    assert job["result"]["optimal"] and job["result"]["depth"] == optimum
                    assert not job.get("fallback_reason") and not job.get("candidate_error"), job
                    assert not job["early_candidate_delivery"]
                    assert job["candidate_thread_quota"] == 1
                    assert any(event["event"] == "native_incumbent_adopted" for event in job["timing_events"])
                    formulas = [initial, job["result"], job["candidate_result"]]
                    formulas += [event for event in job["timing_events"] if "moves" in event]
                    replayed = 0
                    for formula in formulas:
                        if formula.get("moves") is None:
                            continue
                        state = from_facelets(cases[name]["facelets"])
                        for move in formula["moves"]:
                            state = state.apply_move_index(MOVE_INDEX[move])
                        assert state.is_solved() and len(formula["moves"]) == formula.get("depth", formula.get("cost"))
                        replayed += 1
                    result["htm_photos"].append({"case": name, "seconds": time.monotonic() - started,
                        "replayed_formulas": replayed, "initial": initial, "terminal": job})
        finally:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False)
            process.wait(timeout=15)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--htm-photos", action="store_true", help="Verify the default native candidate on two frozen photo states")
    args = parser.parse_args()
    inspect_portable(args.archive)
    if args.destination.exists():
        parser.error("acceptance destination must be new")
    with zipfile.ZipFile(args.archive) as package:
        package.extractall(args.destination)
    root = args.destination / "RubicPhotoSolve"
    manifest = verify(root)
    ps = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                         str(root / "verify_installation.ps1"), "-Root", str(root)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert ps.returncode == 0, ps.stdout + ps.stderr
    result = {"profile": manifest["profile"], "version": manifest["app_version"],
              "asset_count": len(manifest["files"]), "powershell_verification": "passed",
              "http": run(root, [str(root / "RubicPhotoSolve.exe")], manifest["profile"] == "QtmStrong",
                          htm_photos=args.htm_photos)}
    (args.destination / "acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({**result, "http": {key: value for key, value in result["http"].items()
                                        if key != "htm_photos"},
                      "htm_photos": [{"case": row["case"], "seconds": row["seconds"],
                                      "depth": row["terminal"]["result"]["depth"]}
                                     for row in result["http"].get("htm_photos", [])]}))


if __name__ == "__main__":
    main()
