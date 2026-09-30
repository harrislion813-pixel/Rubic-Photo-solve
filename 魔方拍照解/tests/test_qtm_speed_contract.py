from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from cube_app.solvers.qtm import native
from cube_app.solvers.qtm.memory import within_limit
from cube_app.solvers.resource_broker import ResourceBroker


def test_idle_htm_claim_blocks_new_qtm_until_resident_cleanup():
    broker = ResourceBroker(15)
    assert broker.acquire_qtm(threading.Event(), lambda: None, None)
    cleaning, cleaned = threading.Event(), threading.Event()
    def stop():
        cleaning.set()
        assert cleaned.wait(2)
    broker.release_qtm(stop)
    outcomes = []
    def htm():
        outcomes.append(broker.enter_htm())
        broker.leave_htm()
    thread = threading.Thread(target=htm)
    thread.start()
    try:
        assert cleaning.wait(1)
        assert not broker.acquire_qtm(threading.Event(), lambda: None, time.monotonic() + .03)
        assert not outcomes, 'HTM began before resident cleanup'
    finally:
        cleaned.set()
        thread.join(2)
    assert len(outcomes) == 1
    assert not broker.snapshot()['qtm_active']


def test_old_generation_or_idle_epoch_cannot_close_new_request(monkeypatch):
    bridge = native._PersistentNativeSolver()
    bridge._generation = 4
    bridge._idle_epoch = 8
    closed = []
    monkeypatch.setattr(bridge, '_stop_locked', lambda: closed.append(True))
    assert not bridge.evict_generation(3, 8)
    assert not bridge.evict_generation(4, 7)
    bridge._busy = True
    assert not bridge.evict_generation(4, 8)
    assert not closed


def test_mapped_working_set_is_not_hidden_by_small_private_bytes():
    gib = 1 << 30
    assert not within_limit({'working_set':2*gib, 'private_bytes':100 << 20,
                             'available_bytes':8*gib}, gib, 2*gib)
    assert not within_limit({'working_set':100 << 20, 'private_bytes':100 << 20,
                             'available_bytes':gib}, 8*gib, 2*gib)


def test_loading_admission_reserves_mapping_and_idle_never_resumes(monkeypatch):
    bridge = native._PersistentNativeSolver()
    bridge._generation = 3
    bridge._process = SimpleNamespace(pid=123)
    bridge._pending_stage = {'stage':'strong', 'mapped_bytes':2 << 30}
    sent = []
    monkeypatch.setattr(bridge, '_send_locked', sent.append)
    memory = {'working_set':600 << 20, 'private_bytes':100 << 20, 'available_bytes':3 << 30}
    monkeypatch.setattr(native, 'sample_memory', lambda pid: memory)
    bridge._busy = True
    bridge._admit_loader_locked(bridge._process, 3)
    assert sent == ['loader_deny\t3\n'], 'admission ignored mapping plus system reserve'
    sent.clear()
    memory['available_bytes'] = 16 << 30
    bridge._busy = False
    bridge._admit_loader_locked(bridge._process, 3)
    assert not sent, 'idle loader resumed without a CPU lease'
    bridge._busy = True
    bridge._admit_loader_locked(bridge._process, 2)
    assert not sent, 'stale reader resumed the current generation'
    bridge._admit_loader_locked(bridge._process, 3)
    assert sent == ['loader_resume\t3\n']


def test_failed_pause_cannot_retain_process(monkeypatch):
    bridge = native._PersistentNativeSolver()
    bridge._process = SimpleNamespace(poll=lambda:None)
    monkeypatch.setenv('CUBE_QTM_REUSE', 'bounded')
    monkeypatch.setattr(bridge, '_send_locked', lambda message:None)
    monkeypatch.setattr(bridge._loader_paused, 'wait', lambda timeout:False)
    assert not bridge.retain_idle()
    assert bridge._idle_until is None


def test_htm_claim_during_idle_transition_keeps_lease_until_cleanup():
    broker = ResourceBroker(15)
    assert broker.acquire_qtm(threading.Event(), lambda:None, None)
    # This is the moment a waiting HTM claim already cancelled the active QTM.
    with broker._condition:
        broker._htm_holders = 1
    observed = []
    def cleanup():
        observed.append(broker.snapshot()['qtm_active'])
    broker.release_qtm(cleanup)
    assert observed == [True]
    assert not broker.snapshot()['qtm_active'] and not broker.snapshot()['qtm_resident']
    broker.leave_htm()


def test_failed_resident_cleanup_does_not_grant_htm_cpu():
    broker = ResourceBroker(15)
    assert broker.acquire_qtm(threading.Event(), lambda:None, None)
    with broker._condition:
        broker._htm_holders = 1
    def fail():
        raise RuntimeError('injected cleanup fault')
    with pytest.raises(RuntimeError):
        broker.release_qtm(fail)
    assert broker.snapshot()['qtm_active']
    assert broker.snapshot()['yield_faults'] == 1
    broker.leave_htm()
