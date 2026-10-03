"""Read-only check that frozen photos and manual facelets still have their identity."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import from_facelets, to_facelets  # noqa: E402


def main() -> None:
    cases = json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))
    assert [case["name"] for case in cases] == ["initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16"]
    for case in cases:
        assert case["cube_size"] == 3 and case["face_order"] == "URFDLB"
        facelets = "".join(case["faces"][face] for face in "URFDLB")
        assert facelets == case["facelets"]
        assert hashlib.sha256(facelets.encode("ascii")).hexdigest() == case["facelets_sha256"]
        assert to_facelets(from_facelets(facelets)) == facelets
        for face in "URFDLB":
            photo = case["images"][face]
            data = (ROOT / photo["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == photo["sha256"], photo["path"]
            assert len(data) == photo["bytes"]
        review = case["reference_review"]
        assert review["status"] == "visually_verified" and not review["unresolved_ambiguities"]
        assert hashlib.sha256((ROOT / review["reference_path"]).read_bytes()).hexdigest() == review["reference_sha256"]
        assert case["recognition_review"]["status"] == "browser_verified"
        print(f"{case['name']}: 6 photo hashes, manual reference hash and legal facelets verified")


if __name__ == "__main__":
    main()
