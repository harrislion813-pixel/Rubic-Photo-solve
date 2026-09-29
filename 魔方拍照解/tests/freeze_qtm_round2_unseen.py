"""Freeze the round-two holdout before tuning the QTM solver."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark_native import legal_state
from cube_app.cubie import from_facelets, to_facelets


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    excluded = set()
    for name in ("qtm_acceptance_public_cases.json", "qtm_acceptance_cases.json",
                 "native_qtm_pgo_cases.json"):
        for case in json.loads((ROOT / "tests" / name).read_text(encoding="utf-8")):
            if "facelets" in case:
                excluded.add(case["facelets"])
    cases = []
    for seed in range(2026092900, 2026092932):
        cube = legal_state(seed)
        facelets = to_facelets(cube)
        assert from_facelets(facelets) == cube and facelets not in excluded
        excluded.add(facelets)
        cases.append({"name": f"unseen-{seed}", "facelets": facelets,
                      "source": {"kind": "independent_legal_state_rng", "seed": seed},
                      "expected_qtm_depth": None})
    target = ROOT / "tests" / "qtm_round2_unseen_cases.json"
    target.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} disjoint holdout states: {target}")


if __name__ == "__main__":
    main()
