"""Reproduce late incumbent adoption after a verified cached lower bound.

Uses an already known optimal solution only to test protocol behavior; this
is deliberately not a from-scratch performance measurement.
"""
from pathlib import Path
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from benchmark_next_speed_pair import Service
from cube_app.cubie import from_facelets, MOVE_INDEX

if len(sys.argv) != 2:
    raise SystemExit('usage: incumbent_probe.py NEW_OUTPUT_JSON')
output=Path(sys.argv[1]).resolve()
if output.exists():
    raise SystemExit('refusing to overwrite existing diagnostics')
output.parent.mkdir(parents=True,exist_ok=True)

cases=json.loads((ROOT/'tests/initial_solver_cases.json').read_text(encoding='utf-8'))
facelets=next(c['facelets'] for c in cases if c['name']=='initial-12')
historical=json.loads((ROOT/'docs/benchmarks/next-speed-2026-10-02/regression-details.json').read_text(encoding='utf-8'))
moves=next(r['terminal']['result']['moves'] for r in historical if r['metric']=='HTM' and r['label']=='baseline')
cube=from_facelets(facelets)
for m in moves: cube=cube.apply_move_index(MOVE_INDEX[m])
assert cube.is_solved() and len(moves)==17
service=Service(ROOT/'native/htm/build/cube_solver_htm.exe','HTM',['--no-direction-probe'])
out={'scope':'Protocol reproducer with injected independently replayed known optimum and prior verified proof. Not a default request benchmark.', 'facelets':facelets,'moves':moves,'runs':[]}
try:
    for request_id,initial,threads,timeout,late in [('seed-proof',moves,15,5,False),('late-optimum',[],1,1.5,True),('initial-optimum',moves,1,1.5,False)]:
        fields=['solve',request_id,facelets,'20',str(timeout),str(threads),' '.join(initial)]
        start=time.perf_counter()
        service.process.stdin.write('\t'.join(fields)+'\n');service.process.stdin.flush()
        row={'request_id':request_id,'initial_incumbent':initial,'threads':threads,'timeout':timeout,'events':[]}
        out['runs'].append(row)
        sent=False
        while True:
            event=service.event(timeout+10)
            if event.get('request_id')!=request_id:continue
            row['events'].append({'received_seconds':time.perf_counter()-start,**event})
            if late and not sent and event.get('type')=='progress' and event.get('current_depth')==17 and event.get('elapsed_seconds',0)>0.20:
                assert event['completed_depth']==16
                service.process.stdin.write('\t'.join(['incumbent',request_id,' '.join(moves)])+'\n');service.process.stdin.flush()
                row['sent_incumbent_seconds']=time.perf_counter()-start
                sent=True
            if event.get('type') in ('result','error'):
                row['result']=event
                row['wall_seconds']=time.perf_counter()-start
                print(json.dumps({k:v for k,v in row.items() if k!='events'},ensure_ascii=False),flush=True)
                break
        if request_id=='seed-proof':assert row['result'].get('optimal') and row['result']['completed_depth']==16
        if late:assert sent
finally:
    service.close()
    output.write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
