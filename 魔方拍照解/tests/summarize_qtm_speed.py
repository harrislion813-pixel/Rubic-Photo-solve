"""Summarize bounded evidence and freeze the actual dirty implementation."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/benchmarks'


def read(name):
    return json.loads((DATA / name).read_text(encoding='utf-8-sig'))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            h.update(chunk)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def medians(data, variant=None):
    output = {}
    for name in ('pgo16', 'known18'):
        runs = [r for r in data['runs'] if r['case']==name and
                (variant is None or r.get('variant')==variant)]
        assert len(runs)==3
        assert all(not r['result'].get('found') and not r['result'].get('timed_out') for r in runs)
        assert len({r['result']['generated_candidates'] for r in runs})==1
        output[name] = {'median_wall_seconds':statistics.median(r['wall_seconds'] for r in runs),
                        'median_native_seconds':statistics.median(r['result']['elapsed_seconds'] for r in runs),
                        'generated_candidates':runs[0]['result']['generated_candidates'],
                        'completed_depth':runs[0]['result']['completed_depth'],
                        'requested_cost_limit':19 if name=='pgo16' else 18}
    return output


def main():
    frozen = read('qtm-speed-baseline-freeze.json')
    base = medians(read('qtm-speed-fixed-baseline.json'))
    final = medians(read('qtm-speed-final-fixed-layer.json'))
    for name in base:
        assert final[name]['generated_candidates']==base[name]['generated_candidates']
        final[name]['change_percent']=(final[name]['median_wall_seconds']/base[name]['median_wall_seconds']-1)*100
    mechanisms = {}
    for name in ('slice','prefetch'):
        evidence = read(f'qtm-speed-{name}-paired.json')
        a,b = medians(evidence,0),medians(evidence,1)
        mechanisms[name] = {'binary_sha256':evidence['binary_sha256'],'baseline':a,'variant':b,
                            'change_percent':{n:(b[n]['median_wall_seconds']/a[n]['median_wall_seconds']-1)*100 for n in a},
                            'production_enabled':False,'reason':'No stable >=5% wall-clock gain'}
    staged = {}
    for name in ('baseline','final'):
        a=read(f'qtm-speed-staged-{name}.json')
        j=a['final']
        g=j['progress']
        staged[name]={k:j.get(k) for k in ('startup_seconds','first_candidate_seconds','strong_ready_seconds',
                     'strong_adopted_seconds','tail_ready_seconds','tail_adopted_seconds','request_elapsed_seconds','proof_wall_seconds')}
        staged[name].update(completed_depth=g['completed_depth'],generated_candidates=g['generated_candidates'],
                            candidate_cost=j['candidate_result']['depth'])
        staged[name]['events']=[e for e in a['events'] if e['event']['type'] in {'asset_adopted','strong_upgrade','thread_activity'}]
    lifecycle=read('qtm-speed-reuse-lifecycle.json')
    s=lifecycle['scenarios']
    pair=s['unfinished_loader_ttl_and_two_states']
    def memory(e):
        samples=e['diagnostics']['memory_samples']
        return {'wait_seconds':e['wait_seconds'],'max_working_set':max(m['working_set'] for m in samples),
                'max_private_bytes':max(m['private_bytes'] for m in samples),'min_available_bytes':min(m['available_bytes'] for m in samples)}
    reuse={'first_startup_seconds':pair['first']['job']['startup_seconds'],
           'second_startup_seconds':pair['second']['job']['startup_seconds'],
           'first_wall_seconds':pair['first']['wall_seconds'],'second_wall_seconds':pair['second']['wall_seconds'],
           'base_ttl':memory(pair['expiry']),'strong_ttl':memory(s['complete_strong_ttl']['expiry']),
           'strong_idle_htm_wait_seconds':s['strong_idle_to_htm']['htm']['resource_wait_seconds'],
           'busy_loader_htm_wait_seconds':s['busy_loader_to_htm']['htm']['resource_wait_seconds'],
           'stale_idle_epoch_ignored':pair['stale_idle_epoch_ignored'],
           'stale_generation_ignored':s['fault_and_generation']['stale_generation_ignored'],
           'memory_limit_eviction_reason':s['memory_limit_eviction']['diagnostics'].get('eviction_reason'),
           'broker_final':lifecycle['broker_final'],'production_enabled':True}
    reuse['startup_saved_percent']=(1-reuse['second_startup_seconds']/reuse['first_startup_seconds'])*100
    package=read('qtm-speed-package-page-acceptance.json')
    page=[]
    for run in package['runs']:
        j=run['final']
        res=j['residency']
        g=j['progress']
        c=j['candidate_result']
        page.append({'name':run['name'],'cold_or_warm':run['cold_or_warm'],
                     **{k:run.get(k) for k in ('page_candidate_seconds','page_candidate_response_seconds','page_terminal_seconds','page_terminal_response_seconds')},
                     **{k:j.get(k) for k in ('startup_seconds','first_candidate_seconds','candidate_delivery_seconds','strong_ready_seconds','strong_adopted_seconds','tail_ready_seconds','tail_adopted_seconds','proof_wall_seconds','request_elapsed_seconds','resource_hold_seconds')},
                     'candidate_cost':c['depth'],'completed_depth':g['completed_depth'],
                     'certified_lower_bound':g['completed_depth']+1,'gap':c['depth']-g['completed_depth']-1,
                     'strict_optimal':False,'candidate_replayed':run['candidate_replayed'],
                     'generated_candidates':g['generated_candidates'],'peak_working_set':max(m['working_set'] for m in res['memory_samples']),
                     'asset_ready_snapshots':[e for e in res['service_events'] if e['event']['type']=='asset_ready'],
                     'adopted_profile':g['asset_profile'],'resident_state_after_request':res['resident_state']})
    # Failed collector runs still contain genuine one-shot UI observations. Never
    # invent missing HTTP ledger values or rerun these difficult states.
    baseline_ui=[]
    from cube_app.cubie import MOVE_INDEX, from_facelets
    from cube_app.metrics import solution_cost
    cases=json.loads((ROOT/'tests/initial_solver_cases.json').read_text(encoding='utf-8'))
    for name,filename in (('initial-1','qtm-speed-baseline-ui.json'),('initial-12','qtm-speed-baseline12-ui.json')):
        obs=json.loads((ROOT/'.cache'/filename).read_text(encoding='utf-8-sig'))[0]
        cube=from_facelets(next(c['facelets'] for c in cases if c['name']==name))
        moves=obs['solution'].split()
        for move in moves:
            cube=cube.apply_move_index(MOVE_INDEX[move])
        assert cube.is_solved()
        baseline_ui.append({**obs,'candidate_cost':solution_cost(moves,'QTM'),'candidate_replayed':True,
                            'completed_depth':19,'strict_optimal':False,'http_ledger_available':False,
                            'timing_is_observation_upper_bound':True,'not_used_for_cross_version_speed_comparison':True})
    (DATA/'qtm-speed-baseline-page-observations.json').write_text(json.dumps(baseline_ui,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'baseline':base,'final':final,'mechanisms':mechanisms,'staged':staged,'reuse':reuse,
             'package':{'archive_sha256':package['archive_sha256'],'manifest':package['manifest'],'page':page,
                        'htm_after_qtm_wait_seconds':package['final_htm']['resource_wait_seconds']},
             'baseline_page_ledger_limitation':True,'strict_proof_speed_goal_met':False,
             'hot_proof_speed_goal_met':False,'targeted_tests':43,'new_package_build_count':1}
    (DATA/'qtm-speed-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=json.loads((ROOT/'dist/QtmStrong-1.9.0/RubicPhotoSolve/asset-manifest.json').read_text(encoding='utf-8'))
    for name,h in manifest['application_source_sha256'].items():
        assert digest(ROOT/name)['sha256']==h,name
    for engine,info in manifest['native_builds'].items():
        for filename,h in info['source_sha256'].items():
            paths=list((ROOT/f'native/{engine}').glob(f'src/{filename}'))+list((ROOT/f'native/{engine}').glob(f'include/{filename}'))
            assert len(paths)==1 and digest(paths[0])['sha256']==h.lower(),filename
        assert digest(ROOT/f'native/{engine}/build/cube_solver_{engine}.exe')['sha256']==info['binary_sha256'].lower()
    artifacts={name:digest(ROOT/name) for name in frozen['artifacts']}
    for name,old in frozen['artifacts'].items():
        if not name.startswith('native/qtm/'):
            assert artifacts[name]==old,name
    snapshot=ROOT/'.cache/qtm-speed-final'
    snapshot.mkdir(parents=True,exist_ok=True)
    repo=Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=ROOT,text=True).strip())
    patch=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=ROOT)
    (snapshot/'uncommitted.patch').write_bytes(patch)
    source={}
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=repo).decode('utf-8').split('\0')
    for name in files:
        if not name or '/build/' in name or name.endswith('qtm-speed-final-freeze.json'):
            continue
        path=repo/name
        if not path.is_file():
            continue
        target=snapshot/'source'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        source[name]=digest(path)
    for name in ('native/htm/build/build-info.json','native/htm/build/cube_solver_htm.exe',
                 'native/qtm/build/build-info.json','native/qtm/build/cube_solver_qtm.exe'):
        target=snapshot/'artifacts'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,target)
    final_freeze={'frozen_utc':datetime.now(timezone.utc).isoformat(),'worktree':str(ROOT),
                  'head':frozen['head'],'actual_dirty_source':True,'snapshot':str(snapshot),
                  'patch':digest(snapshot/'uncommitted.patch'),'source':source,'artifacts':artifacts,
                  'package':{'path':'dist/QtmStrong-1.9.0/RubicPhotoSolve-1.9.0-QtmStrong-windows-x64.zip',
                             'sha256':package['archive_sha256'],'bytes':2306980881},
                  'manifest_application_sources_verified':len(manifest['application_source_sha256']),
                  'all_asset_and_htm_hashes_unchanged_from_frozen_baseline':True}
    (DATA/'qtm-speed-final-freeze.json').write_text(json.dumps(final_freeze,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'final':final,'mechanism_changes':{k:v['change_percent'] for k,v in mechanisms.items()},
                      'reuse_saved_percent':reuse['startup_saved_percent'],'source_files':len(source),
                      'application_sources_verified':len(manifest['application_source_sha256'])},ensure_ascii=False))


if __name__=='__main__':
    main()
