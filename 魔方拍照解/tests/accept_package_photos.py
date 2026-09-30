"""Run frozen photo files through a package's HTTP detector and browser color classifier."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from accept_isolated_package import ROOT, photo_evidence, request, start


def frontend_image(path: Path) -> tuple[np.ndarray, bytes]:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"cannot decode photo: {path}")
    height, width = image.shape[:2]
    scale = min(1.0, 1600 / max(width, height))
    if scale < 1:
        image = cv2.resize(
            image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA
        )
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError(f"cannot encode photo: {path}")
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR), encoded.tobytes()


def patches(image: np.ndarray, corners: list[list[float]]) -> list[str]:
    height, width = image.shape[:2]
    source = np.array([[x * width, y * height] for x, y in corners], dtype=np.float32)
    target = np.array([[0, 0], [239, 0], [239, 239], [0, 239]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(image, transform, (240, 240), flags=cv2.INTER_LINEAR)
    rgba = cv2.cvtColor(warped, cv2.COLOR_BGR2RGBA)
    output = []
    for row in range(3):
        for column in range(3):
            center_x = round(240 * (column + 0.5) / 3)
            center_y = round(240 * (row + 0.5) / 3)
            if row == 1 and column == 1:
                patch = rgba[center_y - 33 : center_y + 34, center_x - 33 : center_x + 34]
                yy, xx = np.ogrid[-33:34, -33:34]
                patch = patch[np.maximum(np.abs(xx), np.abs(yy)) >= 21]
            else:
                patch = rgba[center_y - 35 : center_y + 36, center_x - 35 : center_x + 36]
            output.append(base64.b64encode(patch.tobytes()).decode("ascii"))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    cases = json.loads((ROOT / "tests" / "initial_solver_cases.json").read_text(encoding="utf-8"))
    inventory = json.loads(
        (ROOT / "docs" / "benchmarks" / "htm-qtm-initial-inventory-2026-09-30.json").read_text(encoding="utf-8")
    )
    output = {"label": args.label, "package": str(package), "cases": []}
    process, base, lines = start(package, "eager")
    try:
        for case in cases:
            images = photo_evidence(case, inventory)
            encoded_patches = {}
            detections = {}
            for face, relative in zip("URFDLB", case["image_paths"]):
                image, jpeg = frontend_image(ROOT / relative)
                data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
                detection = request(base + "/api/detect", {"image": data_url, "cube_size": 3}, timeout=30)
                if not detection.get("ok") or not detection.get("detected"):
                    raise RuntimeError(f"{args.label} {case['name']} {face} detection failed: {detection}")
                detections[face] = detection
                encoded_patches[face] = patches(image, detection["corners"])
            classified = subprocess.run(
                ["node", str(ROOT / "tests" / "classify_real_case.mjs")],
                input=json.dumps(encoded_patches), text=True, encoding="utf-8",
                capture_output=True, check=True,
            )
            classification = json.loads(classified.stdout)
            facelets = "".join(classification["labels"][face] for face in "URFDLB")
            result = {
                "name": case["name"], "images": images, "detections": detections,
                "classification": classification, "facelets": facelets,
                "reference_facelets": case["facelets"],
                "matches_reference": facelets == case["facelets"],
            }
            output["cases"].append(result)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"label": args.label, "case": case["name"],
                              "matches_reference": result["matches_reference"]}), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output["server_log"] = lines
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(item["matches_reference"] for item in output["cases"]):
        raise AssertionError("package photo classification differs from the frozen reference")


if __name__ == "__main__":
    main()
