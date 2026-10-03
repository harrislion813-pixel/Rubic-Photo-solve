"""Freeze six independently reviewed photo states; do not classify or solve.

The human annotation is a checked-in input. This command refreshes identities
only after verifying that input using the independent Python cubie validator.
Optionally merge an actual browser identification report after its run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import from_facelets, permutation_parity, to_facelets  # noqa: E402

EVIDENCE = ROOT / "docs/benchmarks/next-speed-2026-10-02"
FACE_ORDER = "URFDLB"
EXPECTED_NAMES = ["initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recognition", type=Path)
    args = parser.parse_args()
    reference_path = EVIDENCE / "manual-photo-reference.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    assert [case["name"] for case in reference["cases"]] == EXPECTED_NAMES
    recognition = None
    if args.recognition:
        recognition = json.loads(args.recognition.read_text(encoding="utf-8"))
        assert recognition["passed"] and recognition["solveRequests"] == 0
        assert [case["name"] for case in recognition["cases"]] == EXPECTED_NAMES
    cases = []
    report = {"reference_sha256": sha256(reference_path.read_bytes()), "validation": "cube_app.cubie.from_facelets(validate=True), to_facelets round trip; independent of web classifier", "cases": []}
    for annotation in reference["cases"]:
        name = annotation["name"]
        group = name.split("-")[1]
        faces = annotation["faces"]
        facelets = "".join(faces[face] for face in FACE_ORDER)
        if "physical_colors" in annotation:
            translated = {face: "".join(reference["physical_to_face"][color] for color in colors) for face, colors in annotation["physical_colors"].items()}
            assert translated == faces, name
        cube = from_facelets(facelets)
        assert to_facelets(cube) == facelets
        photos = {}
        for face in FACE_ORDER:
            relative = f"initial/{face}{group}.jpg"
            path = ROOT / relative
            original = path.read_bytes()
            image = cv2.imdecode(np.frombuffer(original, np.uint8), cv2.IMREAD_COLOR)
            assert image is not None, relative
            height, width = image.shape[:2]
            scale = min(1.0, 1600 / max(width, height))
            photos[face] = {"path": relative, "sha256": sha256(original), "bytes": len(original), "width": width, "height": height,
                            "frontend_width": round(width * scale), "frontend_height": round(height * scale),
                            "visual_grid_size": 3, "rotation_quarter_turns": 0, "mirrored": False}
        case = {"name": name, "cube_size": 3, "face_order": FACE_ORDER, "faces": faces,
                "facelets": facelets, "facelets_sha256": sha256(facelets.encode("ascii")),
                "reference_source": annotation["reference_origin"],
                "image_paths": [photos[face]["path"] for face in FACE_ORDER],
                "images": photos,
                "reference_review": {"status": "visually_verified", "date": reference["annotation_date"],
                                     "reference_path": reference_path.relative_to(ROOT).as_posix(),
                                     "reference_sha256": report["reference_sha256"],
                                     "grid_path": f"docs/benchmarks/next-speed-2026-10-02/{name}-reference-grid.png",
                                     "overview_path": f"docs/benchmarks/next-speed-2026-10-02/{name}-photo-overview.png",
                                     "notes": annotation["review"], "unresolved_ambiguities": []},
                "legality_validation": {"validator": "cube_app.cubie.from_facelets", "valid": True, "round_trip": True},
                "known_optimal_costs": {"HTM": 18, "QTM": 22} if group == "1" else {"HTM": 17, "QTM": 20} if group == "12" else None}
        if recognition:
            identified = next(item for item in recognition["cases"] if item["name"] == name)
            assert identified["referenceFacelets"] == facelets
            assert identified["correctedFacelets"] == facelets
            case["recognition_review"] = {"status": "browser_verified", "report_path": args.recognition.resolve().relative_to(ROOT).as_posix(),
                                          "automatic_facelets": identified["automaticFacelets"],
                                          "automatic_matches_reference": identified["automaticMatchesReference"],
                                          "manual_corrections": identified["manualCorrections"],
                                          "rotation_corrections": identified["rotationCorrections"]}
        else:
            case["recognition_review"] = {"status": "pending_browser_verification"}
        cases.append(case)
        report["cases"].append({"name": name, "facelets": facelets, "facelets_sha256": case["facelets_sha256"],
                                "cube_size": 3, "cp": cube.cp, "co": cube.co, "ep": cube.ep, "eo": cube.eo,
                                "corner_orientation_sum_mod_3": sum(cube.co) % 3,
                                "edge_orientation_sum_mod_2": sum(cube.eo) % 2,
                                "corner_parity": permutation_parity(cube.cp), "edge_parity": permutation_parity(cube.ep),
                                "counts": {face: facelets.count(face) for face in FACE_ORDER}, "valid": True, "round_trip": True})
    (ROOT / "tests/initial_solver_cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (EVIDENCE / "photo-legality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Six photo cases frozen and independently validated; no solving performed")


if __name__ == "__main__":
    main()
