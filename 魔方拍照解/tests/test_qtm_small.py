from collections import deque

from cube_app.coords import N_FLIP, N_SLICE_COMB, get_corner_perm, get_flip, get_slice_comb, get_twist
from cube_app.cubie import CubieCube, MOVE_INDEX
from cube_app.optimal import OptimalSolver
from cube_app.qtm_small import build_qtm_small_tables, load_qtm_small_tables, save_qtm_small_tables
from cube_app.tables import load_or_build_tables


def test_qtm_small_tables_match_independent_radius_four(tmp_path):
    tables = load_or_build_tables()
    small = load_qtm_small_tables() or build_qtm_small_tables(tables)
    saved = save_qtm_small_tables(small, tmp_path)
    loaded = load_qtm_small_tables(tmp_path)
    assert loaded is not None and saved.stat().st_size > 6_000_000
    assert all(part == expected for part, expected in zip(loaded.parts(), small.parts()))

    quarter_moves = [move for move in range(18) if move % 3 != 1]
    distances = {CubieCube(): 0}
    queue = deque([CubieCube()])
    while queue:
        cube = queue.popleft()
        depth = distances[cube]
        twist, flip, slice_comb, corner = (get_twist(cube), get_flip(cube),
                                            get_slice_comb(cube), get_corner_perm(cube))
        assert loaded.twist_slice[twist * N_SLICE_COMB + slice_comb] <= depth
        assert loaded.flip_slice[flip * N_SLICE_COMB + slice_comb] <= depth
        assert loaded.twist_flip[twist * N_FLIP + flip] <= depth
        assert loaded.corner_perm[corner] <= depth
        if depth == 4:
            continue
        for move in quarter_moves:
            child = cube.apply_move_index(move)
            if child not in distances:
                distances[child] = depth + 1
                queue.append(child)
    assert len(distances) == 11_206

    solver = OptimalSolver(tmp_path)
    solver._qtm_small = loaded
    half = CubieCube().apply_move_index(MOVE_INDEX["R2"])
    htm = solver._phase1_heuristic(tables, get_twist(half), get_flip(half),
                                    get_slice_comb(half), get_corner_perm(half), "HTM")
    qtm = solver._phase1_heuristic(tables, get_twist(half), get_flip(half),
                                    get_slice_comb(half), get_corner_perm(half), "QTM")
    assert htm <= 1 and qtm == 2

    loaded_solver = OptimalSolver(tmp_path)
    loaded_solver._tables = tables
    progress = []
    solved = loaded_solver.solve_cube(half, max_depth=2, timeout_seconds=3,
                                      incumbent_moves=["R2"], progress_callback=progress.append, metric="QTM")
    assert solved.optimal and solved.depth == 2
    assert loaded_solver._qtm_small is not None and progress[0]["lower_bound"] == 2

    with saved.open("r+b") as asset:
        asset.seek(100)
        byte = asset.read(1)
        asset.seek(100)
        asset.write(bytes([byte[0] ^ 1]))
    assert load_qtm_small_tables(tmp_path) is None
