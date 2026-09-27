"""Separate proof-cache retry measurements; never substitute for independent benchmarks."""
from __future__ import annotations

import json
from pathlib import Path
import time


def main():
    # Keep the script runnable directly from the application root.
    import sys
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
    from cube_app.metrics import solution_cost, default_max_depth
    from cube_app.native import NATIVE_EXE, _PersistentNativeSolver, _validated_result
    from cube_app.optimal import invert_moves
    from benchmark_native import file_metadata, peak_memory

    case = next(case for case in json.loads((root / 'tests/native_cases.json').read_text()) if case['name'] == 'repo14')
    cube = CubieCube()
    for move in case['scramble'].split():
        cube = cube.apply_move_index(MOVE_INDEX[move])
    incumbent = invert_moves(case['scramble'].split())
    output = {
        'binary': file_metadata(NATIVE_EXE),
        'case': case['name'], 'facelets': to_facelets(cube), 'threads': 4,
        'timeout_seconds': 2, 'proof_cache_reuse': True, 'runs': [],
    }
    bridge = _PersistentNativeSolver()
    try:
        for metric in ('HTM', 'QTM', 'HTM', 'QTM'):
            progress = []
            started = time.perf_counter()
            payload = bridge.solve(cube, default_max_depth(3, metric), 2, 4, incumbent, None, progress.append, metric=metric)
            result = _validated_result(cube, payload, metric)
            output['runs'].append({
                'metric': metric, 'incumbent_depth': solution_cost(incumbent, metric),
                'wall_seconds': time.perf_counter() - started, 'result': result,
                'first_progress': progress[0] if progress else None,
                'peak_memory_bytes': peak_memory(bridge._process),
            })
    finally:
        bridge.close()
    path = root / 'docs/benchmarks/cache-retries.json'
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{key: run[key] for key in ('metric', 'wall_seconds')} | {'nodes': run['result']['nodes'], 'optimal': run['result']['optimal']} for run in output['runs']]))


if __name__ == '__main__':
    main()
