"""Observe two production-page solves, then verify their terminal HTTP ledgers.

The browser drives the normal UI and its normal one-second polling. This helper
never submits a solve or polls an active job. UI observations arrive via a file.
"""
from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

from accept_isolated_package import extract, photo_evidence, request, sha256, verify_manifest
from cube_app.cubie import MOVE_INDEX, from_facelets
from cube_app.metrics import solution_cost

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--archive', type=Path)
    group.add_argument('--source', type=Path)
    p.add_argument('--destination', type=Path)
    p.add_argument('--cases', default='initial-1,initial-12')
    p.add_argument('--ui-log', type=Path, required=True)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.archive:
        root = extract(args.archive.resolve(), args.destination.resolve())
        manifest = verify_manifest(root)
        command = [str(root/'RubicPhotoSolve.exe')]
    else:
        root = args.source.resolve()
        manifest = {'kind':'frozen actual dirty source replay', 'version':'1.8.0'}
        command = [sys.executable, str(root/'windows_launcher.py')]
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('CUBE_QTM_', 'CUBE_NATIVE_', 'PYTHONPATH')):
            env.pop(key,None)
    env['CUBE_NO_BROWSER'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    process = subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                               text=True,encoding='utf-8',errors='replace',
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    events = queue.Queue()
    lines = []
    def read():
        for line in process.stdout:
            item = {'wall_ms':time.time()*1000,'line':line.rstrip()}
            lines.append(item)
            events.put(item)
        events.put(None)
    threading.Thread(target=read,daemon=True).start()
    base = None
    until = time.monotonic()+30
    while time.monotonic()<until:
        item = events.get(timeout=5)
        assert item is not None, lines
        found = re.search(r'http://127\.0\.0\.1:(\d+)/',item['line'])
        if found:
            base = f'http://127.0.0.1:{found[1]}'
            break
    assert base, lines
    # Observe normal page traffic without extra active-job polls. Frozen console
    # stdout may buffer log_message(), so transport evidence uses a loopback relay.
    transport = []
    upstream_port = int(base.rsplit(':',1)[1])
    class Relay(BaseHTTPRequestHandler):
        def forward(self):
            started = time.time()*1000
            body = self.rfile.read(int(self.headers.get('Content-Length',0)))
            connection = http.client.HTTPConnection('127.0.0.1',upstream_port,timeout=60)
            headers = {k:v for k,v in self.headers.items() if k.lower() not in {'host','connection'}}
            connection.request(self.command,self.path,body=body or None,headers=headers)
            response = connection.getresponse()
            content = response.read()
            self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() not in {'connection','transfer-encoding','content-length'}:
                    self.send_header(key,value)
            self.send_header('Content-Length',str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            connection.close()
            if self.path.startswith('/api/solve'):
                try:
                    payload = json.loads(content)
                except (ValueError,UnicodeError):
                    payload = None
                transport.append({'started_wall_ms':started,'delivered_wall_ms':time.time()*1000,
                                  'method':self.command,'path':self.path,'response':payload})
        do_GET = forward
        do_POST = forward
        def log_message(self,*args):
            pass
    relay = ThreadingHTTPServer(('127.0.0.1',0),Relay)
    threading.Thread(target=relay.serve_forever,daemon=True).start()
    page_base = f'http://127.0.0.1:{relay.server_port}'
    cases = json.loads((ROOT/'tests/initial_solver_cases.json').read_text(encoding='utf-8'))
    cases = [c for c in cases if c['name'] in args.cases.split(',')]
    inventory = json.loads((ROOT/'docs/benchmarks/htm-qtm-initial-inventory-2026-09-30.json').read_text(encoding='utf-8'))
    state = {'base':page_base,'upstream':base,'pid':process.pid,'cases':cases,'ui_log':str(args.ui_log.resolve())}
    args.state.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    report = {'root':str(root),'manifest':manifest,'archive_sha256':sha256(args.archive) if args.archive else None,
              'url':page_base,'upstream':base,'transport':'loopback relay, unchanged production page',
              'timeout_seconds':30,'production_poll_seconds':1,'runs':[],'server_log':lines,'page_transport':transport}
    print(json.dumps({'base':page_base,'cases':[{k:c[k] for k in ('name','facelets')} for c in cases]},ensure_ascii=False),flush=True)
    try:
        until = time.monotonic()+600
        handled = 0
        while handled<len(cases) and time.monotonic()<until:
            ui = json.loads(args.ui_log.read_text(encoding='utf-8')) if args.ui_log.exists() else []
            if len(ui)<=handled:
                time.sleep(.1)
                continue
            observation = ui[handled]
            posts = [item for item in transport if item['method']=='POST' and item['path']=='/api/solve']
            ids = [item['response']['job_id'] for item in posts]
            assert len(ids)>handled and len(posts)>handled, 'UI did not submit/poll the expected job'
            job = request(base+'/api/solve/'+ids[handled])
            assert job['status'] in {'complete','timeout','budget_exhausted'},job
            # A terminal progress response can precede native cleanup by a short interval.
            cleanup_until = time.monotonic()+3
            while job.get('resource_hold_seconds') is None and time.monotonic()<cleanup_until:
                time.sleep(.1)
                job = request(base+'/api/solve/'+ids[handled])
            case = cases[handled]
            assert observation['name']==case['name']
            photos = photo_evidence(case,inventory)
            candidate = job.get('candidate_result')
            result = job.get('result')
            payload = result if result and result.get('optimal') else candidate
            assert payload and payload['moves'],job
            cube = from_facelets(case['facelets'])
            for move in payload['moves']:
                cube = cube.apply_move_index(MOVE_INDEX[move])
            assert cube.is_solved() and solution_cost(payload['moves'],'QTM')==payload['depth']
            assert observation['solution'].split()==payload['moves']
            strict = bool(job['optimal'] and result and result.get('optimal'))
            assert ('严格最短：是' in observation['detail'])==strict
            admitted_ms = posts[handled]['started_wall_ms']
            polls = [item for item in transport if item['path']=='/api/solve/'+ids[handled]]
            deliveries = [item for item in polls if (item['response'] or {}).get('candidate_result')]
            terminals = [item for item in polls if (item['response'] or {}).get('status') in {'complete','timeout','budget_exhausted'}]
            report['runs'].append({'name':case['name'],'facelets':case['facelets'],'photos':photos,
                                  'job_id':ids[handled],'final':job,'ui':observation,
                                  'page_candidate_seconds':(observation['first_candidate_wall_ms']-admitted_ms)/1000,
                                  'page_terminal_seconds':(observation['terminal_wall_ms']-admitted_ms)/1000,
                                  'page_candidate_response_seconds':(deliveries[0]['delivered_wall_ms']-admitted_ms)/1000 if deliveries else None,
                                  'page_terminal_response_seconds':(terminals[0]['delivered_wall_ms']-admitted_ms)/1000 if terminals else None,
                                  'strict_proof_verified':strict,'candidate_replayed':True,
                                  'completed_depth':(job.get('progress') or {}).get('completed_depth'),
                                  'cold_or_warm':'warm' if (job.get('residency') or {}).get('warm_reused') else 'cold'})
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            handled += 1
            print(json.dumps({'case':case['name'],'status':job['status'],'strict':strict,
                              'page_candidate_seconds':report['runs'][-1]['page_candidate_seconds']}),flush=True)
        assert handled==len(cases),'UI acceptance did not finish both states'
        # Reclaim a remaining idle resident through the actual HTM admission path.
        from cube_app.cubie import CubieCube, to_facelets
        facelets = to_facelets(CubieCube().apply_move_index(MOVE_INDEX['R2']))
        report['final_htm'] = request(base+'/api/solve',{'metric':'HTM','facelets':facelets,
                                    'max_depth':1,'timeout_seconds':10})
    finally:
        relay.shutdown()
        process.terminate()
        try:
            process.wait(3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
