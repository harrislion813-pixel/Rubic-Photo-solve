"""Run the two frozen photo states against an extracted Windows package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cube_app.cubie import MOVE_INDEX, from_facelets  # noqa: E402
from cube_app.metrics import solution_cost  # noqa: E402

TERMINAL = {"complete", "timeout", "error", "cancelled", "budget_exhausted"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(url: str, body: dict | None = None, timeout: float = 10) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    method = "POST" if body is not None else "GET"
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return {"http_status": exc.code, **json.load(exc)}


def extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    package = destination / "RubicPhotoSolve"
    if not package.is_dir():
        with zipfile.ZipFile(archive) as source:
            source.extractall(destination)
    if not (package / "RubicPhotoSolve.exe").is_file():
        raise FileNotFoundError(package / "RubicPhotoSolve.exe")
    return package


def verify_manifest(package: Path) -> dict:
    manifest_path = package / "asset-manifest.json"
    if not manifest_path.is_file():
        return {"status": "legacy package has no manifest"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        path = package / relative
        if not path.is_file() or path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
            raise RuntimeError(f"package asset differs from manifest: {relative}")
    if manifest["profile"] == "HtmFull":
        if (package / "native/qtm").exists() or (package / "assets/qtm").exists():
            raise RuntimeError("HTM-only package contains QTM runtime assets")
    return {"status": "verified", "profile": manifest["profile"], "files": len(manifest["files"])}


def start(package: Path, loading: str) -> tuple[subprocess.Popen, str, list[str]]:
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "CUBE_NATIVE_EXE", "CUBE_NATIVE_COORDINATE_CACHE",
                "CUBE_QTM_ASSET_PROFILE"):
        environment.pop(key, None)
    environment["CUBE_NATIVE_ASSET_LOADING"] = loading
    process = subprocess.Popen(
        [str(package / "RubicPhotoSolve.exe")], cwd=package, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: list[str] = []
    events: queue.Queue[str | None] = queue.Queue()

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line.rstrip())
            events.put(line)
        events.put(None)

    threading.Thread(target=read, daemon=True).start()
    until = time.monotonic() + 30
    while time.monotonic() < until:
        try:
            line = events.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            break
        match = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
        if match:
            return process, f"http://127.0.0.1:{match.group(1)}", lines
    process.terminate()
    raise RuntimeError("portable server did not start: " + "\n".join(lines[-8:]))


def photo_evidence(case: dict, inventory: dict) -> list[dict]:
    group = int(case["name"].split("-")[1])
    source_case = next(item for item in inventory["cases"] if item["group"] == group)
    expected = {item["path"]: item["sha256"] for item in source_case["files"]}
    evidence = []
    for relative in case["image_paths"]:
        path = ROOT / relative
        actual = sha256(path)
        if actual != expected[relative]:
            raise RuntimeError(f"photo hash changed: {relative}")
        evidence.append({"path": relative, "sha256": actual})
    if case["facelets"] != "".join(case["faces"][face] for face in "URFDLB"):
        raise RuntimeError("reference facelets do not match face grids")
    return evidence


def run_case(base: str, case: dict, metric: str, limit: float, photos: list[dict]) -> dict:
    started = time.monotonic()
    events = []
    body = {
        "facelets": case["facelets"], "cube_size": 3, "metric": metric,
        "max_depth": 20 if metric == "HTM" else 26, "timeout_seconds": limit,
    }
    first = request(base + "/api/solve", body, timeout=limit)
    events.append({"seconds": time.monotonic() - started, "response": first})
    job_id = first.get("job_id")
    last = first
    while job_id and last.get("status", last.get("proof_status")) not in TERMINAL:
        if time.monotonic() - started >= limit:
            try:
                request(base + f"/api/solve/{job_id}/cancel", {}, timeout=3)
            except Exception:
                pass
            last = {**last, "status": "timeout", "client_deadline": True}
            break
        remaining = limit - (time.monotonic() - started)
        time.sleep(min(0.5, max(0.0, remaining)))
        remaining = limit - (time.monotonic() - started)
        if remaining <= 0:
            continue
        try:
            last = request(base + f"/api/solve/{job_id}", timeout=min(5, remaining))
        except TimeoutError:
            if time.monotonic() - started >= limit:
                continue
            raise
        events.append({"seconds": time.monotonic() - started, "response": last})
    cube = from_facelets(case["facelets"])

    def validate(payload: dict | None) -> dict | None:
        if payload is None or not isinstance(payload.get("moves"), list):
            return None
        moves = payload["moves"]
        state = cube
        for move in moves:
            if move not in MOVE_INDEX:
                return {"executable": False, "reason": f"unknown move: {move}"}
            state = state.apply_move_index(MOVE_INDEX[move])
        cost = solution_cost(moves, metric)
        return {"executable": state.is_solved(), "cost": cost,
                "claimed_depth": payload.get("depth"), "optimal_claim": payload.get("optimal")}

    status = last.get("status", last.get("proof_status"))
    proof = last.get("result") if isinstance(last.get("result"), dict) else last
    candidate = last.get("candidate_result")
    if candidate is None and not proof.get("optimal") and proof.get("moves"):
        candidate = proof
    proof_validation = validate(proof)
    candidate_validation = validate(candidate)
    strict = (status == "complete" and proof_validation is not None
              and proof_validation["executable"] and proof_validation["optimal_claim"] is True
              and proof_validation["cost"] == proof_validation["claimed_depth"])
    if status == "complete" and not strict:
        raise AssertionError(f"invalid strict proof for {case['name']}: {last}")
    return {
        "name": case["name"], "metric": metric, "photos": photos,
        "submitted_facelets": case["facelets"], "request": body,
        "wall_seconds": time.monotonic() - started, "final": last,
        "strict_proof_verified": strict, "proof_validation": proof_validation,
        "candidate_validation": candidate_validation,
        "events": events,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--metric", choices=("HTM", "QTM"), required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--asset-loading", choices=("eager", "staged"), default="eager")
    args = parser.parse_args()
    archive = args.archive.resolve()
    package = extract(archive, args.destination.resolve())
    manifest = verify_manifest(package)
    cases = json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))
    inventory = json.loads((ROOT / "docs/benchmarks/htm-qtm-initial-inventory-2026-09-30.json").read_text(encoding="utf-8"))
    output = {
        "label": args.label, "metric": args.metric, "archive": str(archive),
        "archive_sha256": sha256(archive), "package": str(package),
        "manifest": manifest, "asset_loading": args.asset_loading,
        "timeout_seconds": args.timeout,
        "threads": min(32, max(1, (os.cpu_count() or 1) - 1)), "runs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    process, base, lines = start(package, args.asset_loading)
    try:
        output["url"] = base
        output["capabilities"] = request(base + "/api/capabilities") if args.label.endswith("1") else None
        for case in cases:
            photos = photo_evidence(case, inventory)
            run = run_case(base, case, args.metric, args.timeout, photos)
            output["runs"].append(run)
            args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"label": args.label, "case": case["name"],
                              "status": run["final"].get("status", run["final"].get("proof_status")),
                              "wall_seconds": run["wall_seconds"]}), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output["server_log"] = lines
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
