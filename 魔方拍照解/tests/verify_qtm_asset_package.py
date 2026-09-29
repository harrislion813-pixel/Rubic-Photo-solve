"""Verify a copied QTM asset package and exercise a mixed-metric native service."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from benchmark_native import case_state
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    assets = package / ".cache/native"
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file():
        manifest_path = assets / "qtm-asset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    by_name = {record["name"]: record for record in manifest["assets"]}
    for name, record in by_name.items():
        path = assets / name
        if not path.is_file() or path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise AssertionError(f"asset package hash or size mismatch: {name}")
    fallback_asset = manifest.get("python_fallback_asset")
    if fallback_asset:
        path = package / ".cache" / fallback_asset["name"]
        if (not path.is_file() or path.stat().st_size != fallback_asset["bytes"]
                or sha256(path) != fallback_asset["sha256"]):
            raise AssertionError("Python QTM fallback asset hash or size mismatch")
    binary = package / "native/build/cube_solver.exe"
    if not binary.is_file():
        binary = ROOT / "native/build/cube_solver.exe"
    expected_binary = manifest.get("native_binary_sha256")
    if expected_binary and sha256(binary) != expected_binary:
        raise AssertionError("native binary differs from the asset package manifest")
    htm_assets = assets if (assets / "corner_htm_v2.pdb").is_file() else ROOT / ".cache/native"
    command = [str(binary), "serve",
               "--pdb", str(htm_assets / "corner_htm_v2.pdb"),
               "--phase1-pdb", str(htm_assets / "phase1_sym_htm_v2.pdb"),
               "--qtm-pdb", str(assets / "corner_qtm_v3.pdb"),
               "--qtm-phase1-pdb", str(assets / "phase1_qtm_v3.pdb"),
               "--qtm-tail-pdb", str(assets / ("tail_qtm_depth8_v5.pdb" if manifest["profile"] == "strong"
                                                else "tail_qtm_depth7_v5.pdb"))]
    if manifest["profile"] == "strong":
        command += ["--strong-pdb", str(assets / "strong_qtm_v4_nibble.pdb")]
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        ready = json.loads(process.stdout.readline())
        if (not ready.get("ok") or ready["assets"]["QTM"].get("profile") != manifest["profile"]
                or not ready["assets"]["QTM"]["tail"]):
            raise AssertionError(f"wrong QTM ready capabilities: {ready}")

        def request(identifier: str, cube: CubieCube, metric: str, maximum: int, *, cancel: bool = False) -> dict:
            frame = f"solve\t{identifier}\t{to_facelets(cube)}\t{maximum}\t5\t4\t{metric}\t\n"
            process.stdin.write(frame)
            if cancel:
                process.stdin.write(f"cancel\t{identifier}\n")
            process.stdin.flush()
            while True:
                event = json.loads(process.stdout.readline())
                if event.get("request_id") != identifier or event.get("type") in {"progress", "candidate"}:
                    continue
                if event.get("type") != "result":
                    raise AssertionError(event)
                if event["depth"] >= 0:
                    verified = cube
                    for move in event["moves"]:
                        verified = verified.apply_move_index(MOVE_INDEX[move])
                    if not verified.is_solved() or solution_cost(event["moves"], metric) != event["depth"]:
                        raise AssertionError(f"invalid {metric} solution: {event}")
                return event

        half = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        htm = request("htm", half, "HTM", 1)
        qtm = request("qtm", half, "QTM", 2)
        oracle = json.loads((ROOT / "tests/qtm_acceptance_cases.json").read_text(encoding="utf-8"))[0]
        from cube_app.cubie import from_facelets
        oracle_depth = oracle["expected_qtm_depth"]
        exact = request("oracle", from_facelets(oracle["facelets"]), "QTM", oracle_depth)
        if (htm["depth"], qtm["depth"], exact["depth"]) != (1, 2, oracle_depth) or not all(
            result["optimal"] for result in (htm, qtm, exact)
        ):
            raise AssertionError("packaged mixed-metric exact checks failed")
        pgo_case = next(case for case in json.loads((ROOT / "tests/native_cases.json").read_text(encoding="utf-8"))
                        if case["name"] == "pgo16")
        interrupted = request("cancelled", case_state(pgo_case)[0], "QTM", 26, cancel=True)
        after = request("after-cancel", half, "QTM", 2)
        if after["depth"] != 2 or not after["optimal"]:
            raise AssertionError("native service failed to recover after cancellation")
        print(json.dumps({"ok": True, "profile": manifest["profile"], "assets": len(by_name),
                          "htm_depth": htm["depth"], "qtm_depth": qtm["depth"],
                          "oracle_depth": exact["depth"], "cancel_status": interrupted["status"],
                          "after_cancel_depth": after["depth"]}))
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(timeout=15)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


if __name__ == "__main__":
    main()
