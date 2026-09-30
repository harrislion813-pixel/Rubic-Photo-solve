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
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets  # noqa: E402
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


def run(root, command, qtm):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("CUBE_") and k != "PYTHONPATH"}
    environment.update(CUBE_QTM_ASSET_PROFILE="strong", CUBE_QTM_STRONG_FORMAT="nibble",
                       CUBE_NATIVE_ASSET_LOADING="eager")
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
            assert request(base, "/api/version")["version"] == "1.9.0"
            capabilities = request(base, "/api/capabilities")
            assert capabilities["QTM"] is qtm
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
                    if metric == "QTM" and size == 3:
                        assert response.get("asset_profile") == "strong", response
                    result[f"{size}x{size}-{metric}"] = {"depth": response["depth"],
                        "optimal": response["optimal"], "asset_profile": response.get("asset_profile")}
        finally:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False)
            process.wait(timeout=15)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
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
              "http": run(root, [str(root / "RubicPhotoSolve.exe")], manifest["profile"] == "QtmStrong")}
    (args.destination / "acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
