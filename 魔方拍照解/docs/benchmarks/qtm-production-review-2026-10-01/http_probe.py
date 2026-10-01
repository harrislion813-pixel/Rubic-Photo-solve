"""Bounded review probe, not a browser or release acceptance test."""
# Configure the isolated probe before importing modules that select runtime defaults.
# ruff: noqa: E402
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, urlopen

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / 'server.py').is_file() and (parent / 'cube_app').is_dir())
sys.path.insert(0, str(ROOT))

p = argparse.ArgumentParser()
p.add_argument('--loading', choices=['staged', 'eager'], required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
settings = {
    'CUBE_QTM_ASSET_PROFILE': 'strong', 'CUBE_QTM_STRONG_FORMAT': 'nibble',
    'CUBE_NATIVE_ASSET_LOADING': args.loading, 'CUBE_QTM_REUSE': 'off',
    'CUBE_QTM_STRONG_UPGRADE': 'boundary', 'CUBE_QTM_STRONG_SLICE': 'keep',
    'CUBE_QTM_PREFETCH': 'off', 'CUBE_QTM_LOADER_THREADS': '4',
    'CUBE_QTM_LOADER_BUDGET': 'shared', 'CUBE_NATIVE_EDGE_PDBS': 'off',
    'CUBE_QTM_BASE_IDLE_BYTES': str(1 << 30),
    'CUBE_QTM_STRONG_IDLE_BYTES': str(8 << 30),
    'CUBE_QTM_MEMORY_RESERVE_BYTES': str(2 << 30),
}
os.environ.update(settings)
import server
from cube_app.cubie import from_facelets, MOVE_INDEX
from cube_app.metrics import solution_cost
from cube_app.solvers.qtm import backend, native
from cube_app.solvers.resource_broker import BROKER

events = []
original = native.solve_native
started = time.monotonic()
def traced(*positional, **kwargs):
    callback = kwargs.get('progress_callback')
    def progress(event):
        events.append({'seconds': time.monotonic() - started, 'event': event})
        if callback:
            callback(event)
    kwargs['progress_callback'] = progress
    return original(*positional, **kwargs)
native.solve_native = traced
server.AppHandler.log_message = lambda *a: None
http, port = server.create_server()
thread = threading.Thread(target=lambda: http.serve_forever(poll_interval=.05), daemon=True)
thread.start()
case = next(c for c in json.loads((ROOT/'tests/initial_solver_cases.json').read_text(encoding='utf-8'))
            if c['name'] == 'initial-12')
report = {
    'case': case, 'timeout': 30, 'threads': BROKER.threads, 'settings': settings,
    'binary_sha256': hashlib.sha256(native.NATIVE_EXE.read_bytes()).hexdigest(),
    'cold_or_warm': 'new process; OS file cache not cleared; prior asset reads',
    'scope': 'source HTTP; 100 ms observer polling; not production browser or release ZIP',
    'events': events,
}
try:
    started = time.monotonic()
    request = Request(f'http://127.0.0.1:{port}/api/solve',
        data=json.dumps({'metric': 'QTM', 'facelets': case['facelets'], 'timeout_seconds': 30}).encode(),
        headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=5) as response:
        first = json.load(response)
    report['initial'] = first
    report['initial_response_seconds'] = time.monotonic() - started
    job = backend.BACKEND._jobs[first['job_id']]
    while not job['_done'].is_set() and time.monotonic() < started + 36:
        with urlopen(f'http://127.0.0.1:{port}/api/solve/{first["job_id"]}', timeout=2) as response:
            json.load(response)
        job['_done'].wait(.1)
    assert job['_done'].is_set(), 'cleanup did not finish'
    report['observed_cleanup_seconds'] = time.monotonic() - started
    report['final'] = backend.BACKEND.snapshot(first['job_id'])
    final = report['final']
    answer = final.get('result') or final.get('candidate_result')
    if answer and answer.get('depth') is not None:
        cube = from_facelets(case['facelets'])
        for move in answer['moves']:
            cube = cube.apply_move_index(MOVE_INDEX[move])
        report['replay'] = {'solved': cube.is_solved(), 'cost': solution_cost(answer['moves'], 'QTM')}
        assert report['replay']['solved'] and report['replay']['cost'] == answer['depth']
    report['broker'] = BROKER.snapshot()
    print(json.dumps({k: final.get(k) for k in (
        'status', 'optimal', 'startup_seconds', 'first_candidate_seconds',
        'strong_ready_seconds', 'strong_adopted_seconds', 'tail_adopted_seconds',
        'native_search_seconds', 'request_elapsed_seconds', 'asset_profile')}, ensure_ascii=False), flush=True)
finally:
    native.solve_native = original
    native.release_assets()
    http.shutdown()
    http.server_close()
    thread.join(2)
    report['broker_after_cleanup'] = BROKER.snapshot()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
