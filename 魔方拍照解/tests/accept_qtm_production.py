"""Verify the candidate archive, then exercise its default launcher through the UI."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from accept_isolated_package import ROOT, extract, sha256, verify_manifest
from cube_app.cubie import MOVE_INDEX, from_facelets
from cube_app.metrics import solution_cost


def replay(facelets: str, answer: dict) -> dict:
    state = from_facelets(facelets)
    for move in answer["moves"]:
        state = state.apply_move_index(MOVE_INDEX[move])
    cost = solution_cost(answer["moves"], "QTM")
    assert state.is_solved() and cost == answer["depth"], answer
    return {"solved": True, "cost": cost, "optimal_claim": answer.get("optimal")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = extract(args.archive.resolve(), args.destination.resolve())
    manifest = json.loads((package / "asset-manifest.json").read_text(encoding="utf8"))
    identity = {"archive": str(args.archive.resolve()), "archive_sha256": sha256(args.archive),
                "package": str(package), "manifest": verify_manifest(package),
                "launcher_sha256": sha256(package / "启动魔方求解器.cmd"),
                "exe_sha256": sha256(package / "RubicPhotoSolve.exe"),
                "native_builds": manifest["native_builds"]}
    for relative, expected in manifest["application_source_sha256"].items():
        assert sha256(ROOT / relative) == expected, f"application source mismatch: {relative}"
        if relative.startswith("web/"):
            assert sha256(package / relative) == expected, f"packaged web source mismatch: {relative}"
    for engine, build in manifest["native_builds"].items():
        assert build["portable"] is True
        for directory in ("src", "include"):
            for source in (ROOT / f"native/{engine}/{directory}").rglob("*"):
                if source.is_file():
                    assert sha256(source) == build["source_sha256"][source.name].lower(), source
    identity["source_identity_verified"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    identity_path = args.output.with_name("package-identity.json")
    identity_path.write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf8")
    completed = subprocess.run([str(args.node), str(ROOT / "tests/verify_qtm_production_page.cjs"),
                                str(package), str(args.output.resolve()), str(args.playwright)], check=False)
    report = json.loads(args.output.read_text(encoding="utf8"))
    passed = completed.returncode == 0 and len(report["cases"]) == 2
    for case in report["cases"]:
        final = case.get("afterCleanup") or case.get("final") or {}
        candidates = [event["data"] for event in case["events"] if event["data"].get("moves")]
        candidates += [final[key] for key in ("candidate_result", "result") if final.get(key)]
        case["replays"] = [replay(case["facelets"], answer) for answer in candidates]
        expected = 22 if case["name"] == "initial-1" else 20
        case["strict_proof_verified"] = (final.get("status") == "complete" and final.get("optimal") is True
                                         and final.get("result", {}).get("cost") == expected)
        passed = passed and case["strict_proof_verified"] and bool(case["replays"])
    report["identity"] = str(identity_path.resolve())
    report["passed"] = passed
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    if not passed:
        raise SystemExit("candidate package acceptance failed; original attempts retained")
    print("candidate package identity, two strict proofs, UI and replay passed", flush=True)


if __name__ == "__main__":
    main()
