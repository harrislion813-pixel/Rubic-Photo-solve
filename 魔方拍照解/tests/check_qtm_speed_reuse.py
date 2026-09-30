"""One run per resident lifecycle, with real 20-second idle waits and shallow states."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets  # noqa: E402
from cube_app.solvers.qtm import backend, native  # noqa: E402
from cube_app.solvers.resource_broker import BROKER  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.environ['CUBE_QTM_REUSE'] = 'bounded'
    os.environ['CUBE_QTM_STRONG_UPGRADE'] = 'boundary'
    server.AppHandler.log_message = lambda *args:None
    http, port = server.create_server()
    thread = threading.Thread(target=lambda:http.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    bridge = native._PERSISTENT_SOLVER
    report = {'ttl_seconds':20, 'base_limit_bytes':1 << 30, 'strong_limit_bytes':8 << 30,
              'system_reserve_bytes':2 << 30, 'scenarios':{}}

    def save():
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    def post(metric='QTM', move='R2', timeout=10):
        facelets = to_facelets(CubieCube().apply_move_index(MOVE_INDEX[move]))
        req = Request(f'http://127.0.0.1:{port}/api/solve', data=json.dumps({
            'metric':metric, 'facelets':facelets, 'max_depth':2, 'timeout_seconds':timeout}).encode(),
            headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=4) as response:
            return json.load(response)

    def shallow(move='R2'):
        started = time.monotonic()
        first = post(move=move)
        job = backend.BACKEND._jobs[first['job_id']]
        assert job['_done'].wait(12), 'shallow cleanup timeout'
        final = backend.BACKEND.snapshot(first['job_id'])
        assert final['optimal'] and final['result']['depth'] == 2, final
        return {'wall_seconds':time.monotonic()-started, 'job':final, 'broker':BROKER.snapshot()}

    def wait_evicted():
        started = time.monotonic()
        until = started + 23
        while (bridge._process is not None or BROKER.snapshot()['qtm_resident']) and time.monotonic() < until:
            time.sleep(.05)
        assert bridge._process is None, 'resident not evicted'
        assert not BROKER.snapshot()['qtm_active'] and not BROKER.snapshot()['qtm_resident']
        return {'wait_seconds':time.monotonic()-started, 'diagnostics':bridge.diagnostics(),
                'broker':BROKER.snapshot()}

    try:
        # Two different states measure initialization reuse, not same-state proof caching.
        os.environ['CUBE_NATIVE_ASSET_LOADING'] = 'staged'
        first = shallow('R2')
        assert first['job']['resident_retained'], first
        generation, epoch = bridge._generation, bridge._idle_epoch
        second = shallow('F2')
        assert second['job']['resident_retained'] and bridge._generation == generation
        assert not bridge.evict_generation(generation, epoch), 'old TTL closed the next request'
        report['scenarios']['unfinished_loader_ttl_and_two_states'] = {
            'first':first, 'second':second, 'stale_idle_epoch_ignored':True}
        save()
        report['scenarios']['unfinished_loader_ttl_and_two_states']['expiry'] = wait_evicted()
        save()
        print('unfinished loader: two states and real TTL passed',flush=True)

        os.environ['CUBE_NATIVE_ASSET_LOADING'] = 'eager'
        loaded = shallow('R2')
        assert loaded['job']['resident_retained']
        assert loaded['job']['residency']['assets']['QTM']['strong']
        assert loaded['job']['residency']['assets']['QTM']['tail_depth'] == 8
        report['scenarios']['complete_strong_ttl'] = {'request':loaded}
        save()
        report['scenarios']['complete_strong_ttl']['expiry'] = wait_evicted()
        save()
        print('complete strong: real TTL passed',flush=True)

        # Warm HTM before measuring its additional resource wait.
        warm = post('HTM')
        if warm.get('job_id'):
            assert server.JOBS[warm['job_id']]['_done'].wait(8)
        idle = shallow('F2')
        assert idle['job']['resident_retained']
        started = time.monotonic()
        htm = post('HTM')
        assert htm['optimal'] and htm['depth'] == 1
        assert bridge._process is None
        assert htm['resource_wait_seconds'] <= 1
        report['scenarios']['strong_idle_to_htm'] = {
            'idle':idle, 'htm':htm, 'wall_seconds':time.monotonic()-started, 'broker':BROKER.snapshot()}
        save()

        # Hold a ready shallow request at its client notification to expose the
        # BUSY/loader-to-HTM handoff without launching a deep proof.
        os.environ['CUBE_NATIVE_ASSET_LOADING'] = 'staged'
        ready = threading.Event()
        original = native.solve_native
        def held(*positional, **kwargs):
            callback = kwargs.get('progress_callback')
            def progress(event):
                if callback:
                    callback(event)
                if event.get('type') == 'engine_ready':
                    ready.set()
                    assert kwargs['cancel_event'].wait(3)
            kwargs['progress_callback'] = progress
            return original(*positional, **kwargs)
        native.solve_native = held
        try:
            busy = post()
            assert ready.wait(3)
            htm = post('HTM')
            job = backend.BACKEND._jobs[busy['job_id']]
            assert job['_done'].wait(3)
            assert backend.BACKEND.snapshot(busy['job_id'])['status'] == 'cancelled'
            assert htm['resource_wait_seconds'] <= 1 and bridge._process is None
            report['scenarios']['busy_loader_to_htm'] = {
                'qtm':backend.BACKEND.snapshot(busy['job_id']), 'htm':htm,
                'barrier':'ready shallow request, no deep proof', 'broker':BROKER.snapshot()}
        finally:
            native.solve_native = original
        save()

        # Use actual samples with a deliberately lower limit to exercise eviction.
        memory_request = shallow()
        assert memory_request['job']['resident_retained']
        bridge._memory_limit = 100 << 20
        until = time.monotonic() + 2
        while bridge._process is not None and time.monotonic() < until:
            time.sleep(.05)
        assert bridge._process is None
        report['scenarios']['memory_limit_eviction'] = {'request':memory_request,
            'injected_limit_bytes':100 << 20, 'diagnostics':bridge.diagnostics(), 'broker':BROKER.snapshot()}
        save()

        # A dead service must not be reused; old generation cleanup cannot close its replacement.
        fault = shallow()
        old_generation = bridge._generation
        bridge._process.kill()
        bridge._process.wait(2)
        replacement = shallow('F2')
        assert bridge._generation != old_generation
        assert not bridge.evict_generation(old_generation)
        report['scenarios']['fault_and_generation'] = {'fault':fault, 'replacement':replacement,
                                                       'stale_generation_ignored':True}
        native.release_assets()
        save()
    finally:
        native.release_assets()
        http.shutdown()
        http.server_close()
        thread.join(2)
        report['broker_final'] = BROKER.snapshot()
        save()
    assert not report['broker_final']['qtm_resident'] and not report['broker_final']['qtm_active']
    print('all bounded lifecycle scenarios passed',flush=True)


if __name__ == '__main__':
    main()
