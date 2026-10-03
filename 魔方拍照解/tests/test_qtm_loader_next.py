"""Real constructor checkpoints and production protocol lifecycle gates."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import time

import pytest

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.solvers.qtm import native
from test_native_qtm import ROOT, Service
from test_native_qtm import binary as binary


@pytest.fixture(scope="module")
def loader_gate_binary(tmp_path_factory):
    compiler = shutil.which(os.environ.get("CXX", "g++")) or r"C:\msys64\ucrt64\bin\g++.exe"
    assert Path(compiler).is_file(), "real constructor gate requires a compiler"
    target = tmp_path_factory.mktemp("qtm-loader-gate") / "loader_gate.exe"
    command = [compiler, "-std=c++20", "-O3", "-march=x86-64", "-mtune=generic", "-I", "include",
               "../../tests/qtm_loader_gate.cpp", "src/cube.cpp", "src/symmetry.cpp", "src/strong_coords.cpp",
               "-pthread", "-static", "-o", os.path.relpath(target, ROOT / "native/qtm")]
    compiled = subprocess.run(command, cwd=ROOT / "native/qtm", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return target


def test_real_member_initialization_pause_resume_and_equivalence(loader_gate_binary, record_property):
    completed = subprocess.run([str(loader_gate_binary)], capture_output=True, text=True,
                               encoding="utf-8", timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    for name in ("pause_acknowledged", "resume_complete", "optional_callback_equivalent", "exception_unwinds"):
        assert result[name]
    assert result["executing_while_paused"] == 0 and result["callbacks"] > 2000
    record_property("real_constructor_result", json.dumps(result, sort_keys=True))


def _service(binary):
    assert all(path.is_file() for path in (native.QTM_CORNER_PDB, native.QTM_PHASE1_PDB,
                                          native.QTM_STRONG_PDB_NIBBLE)), "complete assets required, no silent skip"
    return Service(binary, "--qtm-pdb", native.QTM_CORNER_PDB, "--qtm-phase1-pdb", native.QTM_PHASE1_PDB,
                   "--strong-pdb", native.QTM_STRONG_PDB_NIBBLE,
                   "--asset-loading=staged", "--loader-managed", "--loader-threads", "2",
                   "--loader-budget=shared", "--strong-validation=split", "--proof-schedule=strong-first",
                   "--base-proof-window=0", "--no-native-candidate", "--no-proof-cache")


def _assert_paused(service, token):
    service.send("loader_pause", token)
    events = []
    while True:
        event = service.event()
        events.append(event)
        assert event["type"] not in {"asset_ready", "asset_error", "loader_done"}, events
        if event["type"] == "loader_paused":
            assert event["token"] == token and event["paused"] and event["executing"] == 0
            break
    # Real stdout remains quiet while the initialized participant is suspended.
    with pytest.raises(queue.Empty):
        service.lines.get(timeout=.05)
    return events


@pytest.mark.qtm_native
@pytest.mark.qtm_full_assets
def test_real_managed_loader_pause_cancel_resume_and_eof(binary, record_property):
    with _service(binary) as service:
        assert service.event("ready")["assets"]["QTM"]["profile"] == "base"
        assert service.event("loader_stage")["stage"] == "strong"
        service.send("loader_resume", "admitted")
        # Let the actual member initialize, then request quiescence. The C++
        # barrier test above proves this operation inside that member precisely.
        time.sleep(.03)
        pause_events = _assert_paused(service, "active-member")
        case = next(item for item in json.loads((ROOT / "tests/native_cases.json").read_text(encoding="utf-8"))
                    if item["name"] == "known18")
        state = CubieCube()
        for move in case["scramble"].split():
            state = state.apply_move_index(MOVE_INDEX[move])
        service.send("solve", "cancel-paused", to_facelets(state), 26, 3, 4, "QTM", "")
        waiting = service.event("progress")
        while waiting.get("phase") != "waiting_strong":
            waiting = service.event("progress")
        service.send("cancel", "cancel-paused")
        cancelled = service.event("result")
        assert cancelled["status"] == "cancelled" and not cancelled["optimal"]
        assert cancelled["completed_depth"] == waiting["completed_depth"]
        _assert_paused(service, "after-cancel")
        service.send("loader_resume", "finish-strong")
        ready = service.event("asset_ready", timeout=25)
        assert ready["stage"] == "strong" and ready["strong"]
        assert service.event("loader_done")["ok"]
        service.process.stdin.close()
        assert service.process.wait(timeout=5) == 0
        service.reader.join(2)
        service.error_reader.join(2)
        assert not service.reader.is_alive() and not service.error_reader.is_alive()
        record_property("protocol_pause", json.dumps(pause_events))
        record_property("strong_ready", json.dumps(ready))


@pytest.mark.qtm_native
@pytest.mark.qtm_full_assets
def test_real_eof_releases_paused_initialization(binary, record_property):
    with _service(binary) as service:
        service.event("ready")
        service.event("loader_stage")
        service.send("loader_resume", "admitted")
        time.sleep(.03)
        _assert_paused(service, "eof-paused-member")
        started = time.monotonic()
        service.process.stdin.close()
        # Native EOF explicitly resumes and joins the loader, including its
        # real asset verification workers; graceful exit confirms no deadlock.
        assert service.process.wait(timeout=25) == 0
        service.reader.join(2)
        service.error_reader.join(2)
        assert not service.reader.is_alive() and not service.error_reader.is_alive()
        events = []
        while not service.lines.empty():
            event = service.lines.get_nowait()
            if event is not None:
                events.append(event)
        assert any(event["type"] == "asset_ready" and event.get("strong") for event in events), events
        assert any(event["type"] == "loader_done" for event in events), events
        record_property("eof_join_seconds", time.monotonic() - started)
