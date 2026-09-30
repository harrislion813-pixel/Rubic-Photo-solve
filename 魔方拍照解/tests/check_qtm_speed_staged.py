"""One bounded cold HTTP staged request; retain every native stage/proof frame."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402
from cube_app.solvers.qtm import backend, native  # noqa: E402
from cube_app.solvers.resource_broker import BROKER  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert 0 < args.timeout <= 30
    if args.binary:
        native.NATIVE_EXE = args.binary.resolve()
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
    server.AppHandler.log_message = lambda *args:None
    http, port = server.create_server()
    thread = threading.Thread(target=lambda: http.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    case = json.loads((ROOT/'tests/initial_solver_cases.json').read_text(encoding='utf-8'))[0]
    report = {'case': case, 'timeout': args.timeout, 'threads': BROKER.threads,
              'binary': str(native.NATIVE_EXE), 'events': events, 'polling_seconds': .05}
    try:
        started = time.monotonic()
        req = Request(f'http://127.0.0.1:{port}/api/solve',
                      data=json.dumps({'metric':'QTM', 'facelets':case['facelets'],
                                       'timeout_seconds':args.timeout}).encode(),
                      headers={'Content-Type':'application/json'})
        with urlopen(req, timeout=5) as response:
            first = json.load(response)
        report['initial'] = first
        job = backend.BACKEND._jobs[first['job_id']]
        until = started + args.timeout + 6
        while not job['_done'].is_set() and time.monotonic() < until:
            with urlopen(f'http://127.0.0.1:{port}/api/solve/{first["job_id"]}', timeout=2) as response:
                json.load(response)
            job['_done'].wait(.05)
        assert job['_done'].is_set(), 'cleanup did not finish'
        report['final'] = backend.BACKEND.snapshot(first['job_id'])
        report['broker'] = BROKER.snapshot()
        print(json.dumps({k:report['final'].get(k) for k in ('status','startup_seconds','strong_ready_seconds','strong_adopted_seconds','tail_ready_seconds','tail_adopted_seconds','first_candidate_seconds','request_elapsed_seconds')}, ensure_ascii=False), flush=True)
    finally:
        native.solve_native = original
        native.release_assets()
        http.shutdown()
        http.server_close()
        thread.join(2)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
