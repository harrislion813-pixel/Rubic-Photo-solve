"""Q1 gates: independent QTM replay, coordinate/counter equivalence and guarded fallback."""

from __future__ import annotations

import random
import subprocess

import pytest

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.solvers.qtm import native
from test_native_qtm import Service, environment, oracle, replay, run
from test_native_qtm import binary as binary
from test_native_qtm import partial_assets as partial_assets

pytestmark = pytest.mark.qtm_native


@pytest.fixture(scope="module")
def full_strong_flags():
    paths = [native.QTM_CORNER_PDB, native.QTM_PHASE1_PDB, native.QTM_STRONG_PDB_NIBBLE]
    missing = [str(path) for path in paths if not path.is_file()]
    assert not missing, "Q1 complete-asset gate cannot run without: " + ", ".join(missing)
    return ["--qtm-pdb", paths[0], "--qtm-phase1-pdb", paths[1], "--strong-pdb", paths[2],
            "--asset-loading=eager", "--no-native-candidate", "--no-proof-cache", "--direction-policy=off"]


@pytest.mark.qtm_full_assets
def test_full_strong_hotpath_matches_all_cutoffs_and_live_coordinate_fields(binary, full_strong_flags):
    checked = run(binary, "check-heuristic", "--metric", "QTM", "--depth", "2",
                  "--pdb", native.QTM_CORNER_PDB, "--phase1-pdb", native.QTM_PHASE1_PDB,
                  "--strong-pdb", native.QTM_STRONG_PDB_NIBBLE, "--qtm-expansion=full-strong")
    assert checked["ok"] and checked["checked"] == len(oracle(2))
    assert checked["full_strong_checked"] == checked["checked"] * 18 * 31


@pytest.mark.qtm_full_assets
@pytest.mark.parametrize("expansion", ["default", "full-strong"])
def test_full_assets_independent_oracle_and_small_thread_quotas(binary, full_strong_flags, expansion):
    states = [item for item in oracle(3) if item[1] > 0]
    flags = [] if expansion == "default" else ["--qtm-expansion=full-strong"]
    with Service(binary, *full_strong_flags, *flags) as service:
        assert service.event("ready")["assets"]["QTM"]["profile"] == "strong-no-tail"
        for index, (state, distance) in enumerate(random.Random(20261002).sample(states, 12)):
            result = service.solve(state, bound=distance, threads=index % 3 + 1)
            replay(state, result, distance)
            assert result["generated_candidates"] > 0
            assert result["full_strong_expansions"] == (result["generated_candidates"] if flags else 0)


@pytest.mark.qtm_full_assets
@pytest.mark.parametrize("flag", ["--pdb-prefetch=on", "--strong-slice=omit", "--pdb-query-order=legacy",
                                  "--pdb-query-order=interleaved", "--dual-policy=root",
                                  "--coordinate-kernel=reference", "--no-staged-expansion",
                                  "--keep-small-tables", "--no-axis-strengthening", "--qtm-axis-rule=off"])
def test_nondefault_features_retain_generic_expansion(binary, full_strong_flags, flag):
    state = CubieCube().apply_move_index(MOVE_INDEX["R2"])
    with Service(binary, *full_strong_flags, "--qtm-expansion=full-strong", flag) as service:
        service.event("ready")
        result = service.solve(state, bound=2)
        replay(state, result, 2)
        assert result["generated_candidates"] > 0 and result["full_strong_expansions"] == 0


@pytest.mark.qtm_full_assets
def test_specialized_search_keeps_cancellation_and_absolute_deadline(binary, full_strong_flags):
    state = CubieCube()
    for move in "U' F L R' D' B' F U' B2 L D R2 B2 L2 U2 L' U2 R'".split():
        state = state.apply_move_index(MOVE_INDEX[move])
    with Service(binary, *full_strong_flags, "--qtm-expansion=full-strong") as service:
        service.event("ready")
        service.send("solve", "cancel-hotpath", to_facelets(state), 26, 2, 1, "QTM", "")
        while True:
            event = service.event()
            assert event.get("type") != "result", "cancellation case finished before requesting cancellation"
            if event.get("type") == "progress" and event.get("full_strong_expansions", 0) > 0:
                break
        service.send("cancel", "cancel-hotpath")
        cancelled = service.event("result")
        assert cancelled["status"] == "cancelled" and not cancelled["optimal"]
        assert cancelled["full_strong_expansions"] > 0 and cancelled["completed_depth"] < 26
        expired = service.solve(state, bound=26, timeout=.02, threads=1, request_id="expire-hotpath")
        assert expired["status"] == "timeout" and not expired["optimal"]
        assert expired["full_strong_expansions"] > 0 and expired["completed_depth"] < 26


def test_missing_partial_and_corrupt_assets_keep_the_generic_path(binary, partial_assets, tmp_path):
    corrupt = tmp_path / "strong.pdb"
    corrupt.write_bytes(b"invalid strong QTM asset")
    configurations = [[], ["--qtm-pdb", partial_assets["corner"], "--qtm-phase1-pdb", partial_assets["phase1"]],
                      ["--strong-pdb", corrupt, "--asset-loading=eager"]]
    state = CubieCube().apply_move_index(MOVE_INDEX["F2"])
    for flags in configurations:
        with Service(binary, *flags, "--no-native-candidate", "--no-proof-cache", "--direction-policy=off",
                     "--qtm-expansion=full-strong") as service:
            service.event("ready")
            result = service.solve(state, bound=2)
            replay(state, result, 2)
            assert result["full_strong_expansions"] == 0


def test_full_strong_diagnostic_requires_complete_assets(binary):
    checked = subprocess.run([str(binary), "check-heuristic", "--metric", "QTM", "--depth", "0",
                              "--qtm-expansion=full-strong"], env=environment(), capture_output=True,
                             text=True, encoding="utf-8", timeout=25)
    assert checked.returncode != 0 and "requires complete QTM" in checked.stderr
