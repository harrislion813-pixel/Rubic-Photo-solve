from __future__ import annotations

import json
import threading
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import server
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost
from cube_app.native import NativeSolverError, NativeSolverTimeout
from cube_app.optimal import SolveResult


def after(sequence):
    cube = CubieCube()
    for move in sequence.split():
        cube = cube.apply_move_index(MOVE_INDEX[move])
    return cube


@pytest.fixture
def jobs():
    before = set(server.JOBS)
    yield
    with server.JOBS_LOCK:
        for key in set(server.JOBS) - before:
            server.JOBS[key]['_cancel_event'].set()
    for key in set(server.JOBS) - before:
        worker = server.JOBS[key]['_worker']
        if worker.ident is not None:
            worker.join(5)
    with server.JOBS_LOCK:
        for key in set(server.JOBS) - before:
            server.JOBS.pop(key, None)


@pytest.fixture
def api(jobs):
    http = server.ExclusiveThreadingHTTPServer((server.HOST, 0), server.AppHandler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()

    def request(payload, suffix=''):
        req = Request(f'http://{server.HOST}:{http.server_address[1]}/api/solve{suffix}',
                      data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    yield request
    http.shutdown()
    http.server_close()
    worker.join(2)


@pytest.mark.parametrize('metric,depth', [('HTM', 1), ('QTM', 2)])
def test_http_python_search_prices_half_turn(api, metric, depth):
    with patch.object(server, 'native_solver_available', return_value=False):
        status, result = api({'facelets': to_facelets(after('R2')), 'metric': metric, 'timeout_seconds': 3})
    assert status == 200
    assert result['metric'] == metric
    assert result['depth'] == depth
    assert result['optimal'] and result['proof_status'] == 'complete'
    cube = after('R2')
    for move in result['moves']:
        cube = cube.apply_move_index(MOVE_INDEX[move])
    assert cube.is_solved()


@pytest.mark.parametrize('metric', ['HTM', 'QTM'])
def test_zero_result_keeps_request_metric(api, metric):
    with patch.object(server, 'native_solver_available', return_value=False):
        status, result = api({'facelets': to_facelets(CubieCube()), 'metric': metric, 'max_depth': 0})
    assert status == 200
    assert result['metric'] == metric and result['depth'] == 0 and result['optimal']


@pytest.mark.parametrize('extra', [
    {'metric': 'STM'}, {'metric': None}, {'metric': 1}, {'metric': 'HTM', 'max_depth': 21},
    {'metric': 'QTM', 'max_depth': 27}, {'metric': 'QTM', 'max_depth': 2.5},
    {'max_depth': True}, {'max_depth': '2'}, {'max_depth': -1},
])
def test_http_rejects_invalid_metric_and_budget(api, extra):
    status, result = api({'facelets': to_facelets(CubieCube()), **extra})
    assert status == 400 and not result['ok']


@pytest.mark.parametrize('size,metric,expected', [(2, 'HTM', 11), (2, 'QTM', 14), (3, 'HTM', 20), (3, 'QTM', 26)])
def test_http_defaults_follow_size_and_metric(api, size, metric, expected):
    result = SolveResult([], 0, metric, 0, True)
    target = server.TWO_BY_TWO_SOLVER if size == 2 else server.PROBE_SOLVER
    method = 'solve_facelets' if size == 2 else 'solve_cube'
    with patch.object(server, 'native_solver_available', return_value=False), patch.object(target, method, return_value=result) as solve:
        status, payload = api({'facelets': to_facelets(CubieCube()), 'cube_size': size, 'metric': metric})
    assert status == 200 and payload['metric'] == metric
    assert solve.call_args.kwargs['max_depth'] == expected
    assert solve.call_args.kwargs['metric'] == metric


def test_active_job_keys_isolate_metric_budget_and_proof_version(jobs):
    cube = after('R2 U')
    htm, htm_worker = server.prepare_optimal_job(cube, None, 20, 3)
    qtm, _ = server.prepare_optimal_job(cube, None, 26, 3, metric='QTM')
    htm_retry, retry = server.prepare_optimal_job(cube, None, 20, 3, metric='htm')
    qtm_small, _ = server.prepare_optimal_job(cube, None, 20, 3, metric='QTM')
    assert htm == htm_retry and htm_worker is retry
    assert len({htm, qtm, qtm_small}) == 3
    assert server.JOBS[qtm]['metric'] == 'QTM'
    assert server.JOBS[qtm]['proof_version'] == 2


def test_candidates_compare_weighted_cost_not_item_count(jobs):
    # Both restore R2. The 3-token candidate costs 6 QTM; the 4-token candidate costs 4.
    fewer = ['R2', 'U2', 'U2']
    cheaper = ['R', 'R', 'U', "U'"]
    for moves in (fewer, cheaper):
        cube = after('R2')
        for move in moves:
            cube = cube.apply_move_index(MOVE_INDEX[move])
        assert cube.is_solved()
    quick = SolveResult(fewer, 3, 'HTM', 0, False)
    key, _ = server.prepare_optimal_job(after('R2'), quick, 26, 3, metric='QTM')
    assert server.JOBS[key]['incumbent_depth'] == 6
    server.update_job_candidate(key, SolveResult(cheaper, 4, 'HTM', 0, False))
    server.update_job_candidate(key, quick)
    assert server.JOBS[key]['_incumbent_moves'] == cheaper
    assert server.JOBS[key]['candidate_result']['depth'] == 4
    assert not server.JOBS[key]['candidate_result']['optimal']


def test_qtm_engine_failure_falls_back_with_same_metric_deadline_and_cost(jobs):
    candidate = SolveResult(['R2'], 1, 'HTM', 0, False)
    with patch.object(server, 'solve_native', side_effect=NativeSolverError('protocol outdated')), patch.object(
        server.SOLVER, 'solve_cube', return_value=SolveResult(['R2'], 2, 'QTM', 0, True)
    ) as solve:
        key, worker = server.prepare_optimal_job(after('R2'), candidate, 26, 3, metric='QTM')
        worker.start()
        worker.join(5)
    assert server.JOBS[key]['status'] == 'complete'
    assert solve.call_args.kwargs['metric'] == 'QTM'
    assert solve.call_args.kwargs['upper_bound'] == 2
    assert solve.call_args.kwargs['deadline'] == server.JOBS[key]['_deadline']


def test_qtm_native_timeout_does_not_start_python(jobs):
    with patch.object(server, 'solve_native', side_effect=NativeSolverTimeout('timeout')), patch.object(
        server.SOLVER, 'solve_cube'
    ) as solve:
        key, worker = server.prepare_optimal_job(after('R2'), None, 26, 3, metric='QTM')
        worker.start()
        worker.join(5)
    assert server.JOBS[key]['status'] == 'timeout' and server.JOBS[key]['metric'] == 'QTM'
    solve.assert_not_called()


def test_nonoptimal_native_candidate_is_budget_exhausted(jobs):
    result = {'moves': ['R2'], 'depth': 2, 'metric': 'QTM', 'optimal': False}
    with patch.object(server, 'solve_native', return_value=result):
        key, worker = server.prepare_optimal_job(after('R2'), None, 1, 3, metric='QTM')
        worker.start()
        worker.join(5)
    assert server.JOBS[key]['status'] == 'budget_exhausted'
    assert not server.JOBS[key]['result']['optimal']
    assert server.JOBS[key]['result']['depth'] == solution_cost(result['moves'], 'QTM')


def test_task_and_cancel_snapshots_keep_metric(api):
    key, _ = server.prepare_optimal_job(after('R2'), None, 26, 3, metric='QTM')
    status, task = api(None, '/' + key)
    assert status == 200 and task['metric'] == 'QTM' and task['max_depth'] == 26
    status, cancelled = api({}, '/' + key + '/cancel')
    assert status == 200 and cancelled['metric'] == 'QTM' and cancelled['status'] == 'cancelled'


def test_http_qtm_budget_one_is_incomplete_not_invalid_state(api):
    with patch.object(server, 'native_solver_available', return_value=False):
        status, result = api({'facelets': to_facelets(after('R2')), 'metric': 'QTM', 'max_depth': 1})
    assert status == 200 and result['ok']
    assert result['metric'] == 'QTM' and not result['optimal']
    assert result['depth'] is None and result['proof_status'] == 'budget_exhausted'


@pytest.mark.parametrize('metric,depth', [('HTM', 1), ('QTM', 2)])
def test_http_two_by_two_real_distance_table(api, metric, depth):
    from cube_app.two_by_two import is_solved_2x2, to_facelets_2x2
    status, result = api({'facelets': to_facelets_2x2(after('R2')), 'cube_size': 2, 'metric': metric})
    assert status == 200 and result['metric'] == metric and result['depth'] == depth
    assert result['optimal'] and result['proof_status'] == 'complete'
    cube = after('R2')
    for move in result['moves']:
        cube = cube.apply_move_index(MOVE_INDEX[move])
    assert is_solved_2x2(cube)


@pytest.mark.native_pdb
def test_http_native_qtm_under_budget_keeps_incomplete_status(api):
    if not server.native_solver_available():
        pytest.skip('compiled solver and required PDBs are unavailable')
    status, result = api({'facelets': to_facelets(after('R2')), 'metric': 'QTM', 'max_depth': 1})
    assert status == 200 and result['metric'] == 'QTM'
    assert not result['optimal'] and result['depth'] is None
    assert result['proof_status'] == 'budget_exhausted'
    status, job = api(None, '/' + result['job_id'])
    assert status == 200 and job['metric'] == 'QTM' and job['status'] == 'budget_exhausted'
    assert not job['result']['optimal']
