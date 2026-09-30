"""Three interleaved pairs, identical binary/assets, one mechanism per comparison."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark_isolation_short import fixed_layer, sha256  # noqa: E402


class Service:
    def __init__(self, command):
        env = os.environ.copy()
        env['CUBE_NATIVE_COORDINATE_CACHE'] = str(ROOT/'.cache/qtm/coordinates_dual_v2.bin')
        self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.events = queue.Queue()
        self.errors = []
        def read():
            for line in self.process.stdout:
                self.events.put(json.loads(line))
            self.events.put(None)
        def errors():
            self.errors.extend(self.process.stderr)
        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=errors, daemon=True).start()
        self.ready = self.events.get(timeout=40)
        assert self.ready and self.ready.get('type') == 'ready', self.errors

    def run(self, facelets, bound, request_id):
        started = time.perf_counter()
        self.process.stdin.write(f'solve\t{request_id}\t{facelets}\t{bound}\t5\t15\tQTM\t\n')
        self.process.stdin.flush()
        frames = []
        while True:
            event = self.events.get(timeout=10)
            assert event is not None, self.errors
            if event.get('request_id') != request_id:
                continue
            if event['type'] not in {'result', 'error'}:
                frames.append(event)
                continue
            run = {'bound':bound, 'wall_seconds':time.perf_counter()-started, 'progress':frames, 'result':event}
            run['fixed_layer'] = fixed_layer(run)
            run['seconds_per_million'] = event['elapsed_seconds'] * 1e6 / event['generated_candidates']
            return run

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mechanism', choices=['slice', 'prefetch'], required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    frozen = json.loads((ROOT/'docs/benchmarks/qtm-speed-fixed-baseline.json').read_text(encoding='utf-8'))
    binary = ROOT/'native/qtm/build/cube_solver_qtm.exe'
    base = [str(binary), 'serve', '--asset-loading=eager', '--no-proof-cache', '--no-native-candidate',
            '--direction-policy=off', '--dual-policy=off', '--pdb-query-order=strong-first']
    for flag, name in [('--pdb','corner_htm_v2.pdb'), ('--phase1-pdb','phase1_sym_htm_v2.pdb'),
                       ('--qtm-pdb','corner_qtm_v3.pdb'), ('--qtm-phase1-pdb','phase1_qtm_v3.pdb'),
                       ('--strong-pdb','strong_qtm_v4_nibble.pdb'), ('--qtm-tail-pdb','tail_qtm_depth8_v5.pdb')]:
        base += [flag, str(ROOT/'assets/qtm/v1'/name)]
    flags = ['--strong-slice=omit'] if args.mechanism == 'slice' else ['--pdb-prefetch=on']
    report = {'mechanism':args.mechanism, 'binary_sha256':sha256(binary), 'command':base,
              'variant_flags':flags, 'baseline_freeze':'qtm-speed-baseline-freeze.json',
              'cases':frozen['cases'], 'runs':[]}
    services = []
    try:
        for command in (base, base+flags):
            services.append(Service(command))
        report['ready'] = [s.ready for s in services]
        for repeat in range(3):
            for case in frozen['cases']:
                paired = []
                for variant in ([0, 1] if repeat % 2 == 0 else [1, 0]):
                    bound = 19 if case['name'] == 'pgo16' else 18
                    run = services[variant].run(case['facelets'], bound, f'{repeat}-{variant}-{case["name"]}')
                    run.update(case=case['name'], repeat=repeat, variant=variant)
                    report['runs'].append(run)
                    paired.append(run)
                    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(json.dumps({k:run[k] for k in ('case','repeat','variant','wall_seconds')}),flush=True)
                assert paired[0]['result']['generated_candidates'] == paired[1]['result']['generated_candidates']
                if args.mechanism == 'slice':
                    for run in paired:
                        assert run['result']['strong_prefetches'] == 0
                        assert bool(run['result']['slice_updates_skipped']) == bool(run['variant'])
                else:
                    for run in paired:
                        assert bool(run['result']['strong_prefetches']) == bool(run['variant'])
    finally:
        for service in services:
            service.close()
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
