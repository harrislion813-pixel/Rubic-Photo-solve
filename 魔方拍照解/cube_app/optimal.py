from __future__ import annotations

import multiprocessing
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Callable

from .coords import (
    N_FLIP,
    N_SLICE_COMB,
    N_SLICE_PERM,
    get_corner_perm,
    get_flip,
    get_slice_comb,
    get_twist,
    perm_to_rank,
)
from .cubie import (
    CubeStateError,
    CubieCube,
    MOVE_FACE_INDEX,
    MOVE_NAMES,
    PHASE2_MOVES,
    all_move_cubes,
    build_sticker_geometry,
    from_facelets,
    to_facelets,
)
from .tables import SolverTables, load_or_build_tables


_Vector = tuple[int, int, int]


def _rotate_x(vector: _Vector) -> _Vector:
    """Rotate a vector 90 degrees around the positive x axis."""
    x, y, z = vector
    return x, -z, y


def _rotate_z(vector: _Vector) -> _Vector:
    """Rotate a vector 90 degrees around the positive z axis."""
    x, y, z = vector
    return -y, x, z


_SEARCH_ROTATIONS: tuple[Callable[[_Vector], _Vector], ...] = (_rotate_x, _rotate_z)
_NORMAL_TO_FACE = {
    (0, 1, 0): "U",
    (1, 0, 0): "R",
    (0, 0, 1): "F",
    (0, -1, 0): "D",
    (-1, 0, 0): "L",
    (0, 0, -1): "B",
}
_FACE_TO_NORMAL = {face: normal for normal, face in _NORMAL_TO_FACE.items()}


def _conjugate_cube(cube: CubieCube, rotation: Callable[[_Vector], _Vector]) -> CubieCube:
    """Return an equivalent cube viewed through a whole-cube rotation.

    Sticker positions and color labels are rotated together, so the solved cube
    remains solved.  Distances read from the existing pruning tables are
    therefore still admissible in the original orientation.
    """
    sticker_to_index, index_to_sticker = build_sticker_geometry()
    old_facelets = to_facelets(cube)
    new_facelets = [""] * 54
    color_map = {
        face: _NORMAL_TO_FACE[rotation(normal)]
        for face, normal in _FACE_TO_NORMAL.items()
    }
    for old_idx, (position, normal) in enumerate(index_to_sticker):
        new_idx = sticker_to_index[(rotation(position), rotation(normal))]
        new_facelets[new_idx] = color_map[old_facelets[old_idx]]
    return from_facelets("".join(new_facelets))


@lru_cache(maxsize=1)
def _rotation_move_maps() -> tuple[tuple[int, ...], ...]:
    """Map each original move to its conjugate in every search orientation."""
    moves = all_move_cubes()
    move_to_index = {move: idx for idx, move in enumerate(moves)}
    return tuple(
        tuple(move_to_index[_conjugate_cube(move, rotation)] for move in moves)
        for rotation in _SEARCH_ROTATIONS
    )


def _build_allowed_moves() -> tuple[tuple[tuple[int, int], ...], ...]:
    """Precompute canonical successors for last faces 0..5 and no last face."""
    options: list[tuple[tuple[int, int], ...]] = []
    opposite = (3, 4, 5, 0, 1, 2)
    for last_face in (*range(6), None):
        allowed: list[tuple[int, int]] = []
        for move_idx, face in enumerate(MOVE_FACE_INDEX):
            if last_face is not None:
                if face == last_face:
                    continue
                if opposite[last_face] == face and last_face > face:
                    continue
            allowed.append((move_idx, face))
        options.append(tuple(allowed))
    return tuple(options)


_ALLOWED_MOVES = _build_allowed_moves()
_PHASE2_COLUMN = {move_idx: column for column, move_idx in enumerate(PHASE2_MOVES)}
_ALLOWED_PHASE2_MOVES = tuple(
    tuple((_PHASE2_COLUMN[move_idx], move_idx, face) for move_idx, face in moves if move_idx in _PHASE2_COLUMN)
    for moves in _ALLOWED_MOVES
)
_TRANSPOSITION_LIMIT = 2_000_000
_PARALLEL_MIN_DEPTH = 12


@lru_cache(maxsize=1)
def _edge_pack_move_specs() -> tuple[tuple[int, tuple[tuple[int, int], ...]], ...]:
    """Masks and shifts for updating a packed edge permutation in four moves."""
    full_mask = (1 << 48) - 1
    specs: list[tuple[int, tuple[tuple[int, int], ...]]] = []
    for move in all_move_cubes():
        unchanged_mask = full_mask
        shifts: list[tuple[int, int]] = []
        for destination, source in enumerate(move.ep):
            if destination == source:
                continue
            unchanged_mask &= ~(0xF << (destination * 4))
            shifts.append((source * 4, destination * 4))
        specs.append((unchanged_mask, tuple(shifts)))
    return tuple(specs)


def _pack_edges(cube: CubieCube) -> int:
    packed = 0
    for position, edge in enumerate(cube.ep):
        packed |= edge << (position * 4)
    return packed


def _move_edge_pack(packed: int, move_idx: int) -> int:
    unchanged_mask, shifts = _edge_pack_move_specs()[move_idx]
    result = packed & unchanged_mask
    for source_shift, destination_shift in shifts:
        result |= ((packed >> source_shift) & 0xF) << destination_shift
    return result


def _transposition_key(
    edge_pack: int,
    corner_perm: int,
    twist: int,
    flip: int,
    last_face: int,
) -> int:
    packed = (((edge_pack << 16) | corner_perm) << 12) | twist
    packed = (packed << 11) | flip
    return (packed << 3) | last_face


class SearchTimeout(TimeoutError):
    """Raised when optimal search exceeds the requested time limit."""


@dataclass(slots=True)
class SolveResult:
    moves: list[str]
    depth: int
    metric: str
    elapsed_seconds: float
    optimal: bool

    @property
    def text(self) -> str:
        return " ".join(self.moves)


class OptimalSolver:
    def __init__(
        self,
        cache_dir: str | Path = ".cache",
        *,
        parallel: bool = False,
        max_workers: int | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self._tables: SolverTables | None = None
        self.parallel = parallel
        self.max_workers = max_workers or min(12, max(1, (os.cpu_count() or 1) - 1))

    @property
    def tables(self) -> SolverTables:
        if self._tables is None:
            self._tables = load_or_build_tables(self.cache_dir)
        return self._tables

    def solve_facelets(
        self,
        facelets: str,
        max_depth: int = 20,
        timeout_seconds: float | None = 120.0,
        upper_bound: int | None = None,
    ) -> SolveResult:
        cube = from_facelets(facelets)
        return self.solve_cube(cube, max_depth=max_depth, timeout_seconds=timeout_seconds, upper_bound=upper_bound)

    def solve_cube(
        self,
        cube: CubieCube,
        max_depth: int = 20,
        timeout_seconds: float | None = 120.0,
        upper_bound: int | None = None,
    ) -> SolveResult:
        start = time.monotonic()
        deadline = None if timeout_seconds is None else start + timeout_seconds

        if cube.is_solved():
            return SolveResult([], 0, "HTM", time.monotonic() - start, True)

        effective_max = max_depth
        if upper_bound is not None:
            effective_max = min(max_depth, upper_bound - 1)

        tables = self.tables
        state = self._prepare_phase1_state(cube, tables)
        *coords, lower = state
        transposition: dict[int, int] = {}
        pool: Pool | None = None
        try:
            for depth in range(lower, effective_max + 1):
                if self.parallel and self.max_workers > 1 and depth >= _PARALLEL_MIN_DEPTH:
                    if pool is None:
                        context = multiprocessing.get_context("spawn")
                        pool = context.Pool(
                            processes=self.max_workers,
                            initializer=_initialize_search_worker,
                            initargs=(str(self.cache_dir),),
                        )
                    result = self._search_parallel_depth(cube, depth, deadline, pool)
                else:
                    result = self._search_phase1(
                        *coords,
                        lower,
                        depth,
                        6,
                        [],
                        deadline,
                        tables,
                        transposition,
                    )
                if result is not None:
                    moves = [MOVE_NAMES[idx] for idx in result]
                    return SolveResult(moves, len(moves), "HTM", time.monotonic() - start, True)
        finally:
            if pool is not None:
                pool.terminate()
                pool.join()

        raise CubeStateError(f"在 HTM {max_depth} 步内未找到解法。请检查输入状态是否合法。")

    def _prepare_phase1_state(self, cube: CubieCube, tables: SolverTables) -> tuple[int, ...]:
        twist = get_twist(cube)
        flip = get_flip(cube)
        slice_comb = get_slice_comb(cube)
        corner_perm = get_corner_perm(cube)
        edge_pack = _pack_edges(cube)
        rotated_cubes = tuple(_conjugate_cube(cube, rotation) for rotation in _SEARCH_ROTATIONS)
        rotated_coords = tuple(
            (get_twist(view), get_flip(view), get_slice_comb(view), get_corner_perm(view))
            for view in rotated_cubes
        )
        (x_twist, x_flip, x_slice, x_corner_perm), (z_twist, z_flip, z_slice, z_corner_perm) = rotated_coords
        lower = max(
            self._phase1_heuristic(tables, twist, flip, slice_comb, corner_perm),
            self._phase1_heuristic(tables, x_twist, x_flip, x_slice, x_corner_perm),
            self._phase1_heuristic(tables, z_twist, z_flip, z_slice, z_corner_perm),
        )
        return (
            twist,
            flip,
            slice_comb,
            corner_perm,
            edge_pack,
            x_twist,
            x_flip,
            x_slice,
            x_corner_perm,
            z_twist,
            z_flip,
            z_slice,
            z_corner_perm,
            lower,
        )

    def _search_parallel_depth(
        self,
        cube: CubieCube,
        depth: int,
        deadline: float | None,
        pool: Pool,
    ) -> list[int] | None:
        remaining_timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
        if remaining_timeout == 0.0:
            self._check_deadline(deadline)
        tasks = ((cube, depth, move_idx, remaining_timeout) for move_idx in range(18))
        results = pool.imap_unordered(_search_worker_branch, tasks, chunksize=1)
        for _ in range(18):
            try:
                if deadline is None:
                    status, result = next(results)
                else:
                    wait_seconds = deadline - time.monotonic()
                    if wait_seconds <= 0:
                        raise multiprocessing.TimeoutError
                    status, result = results.next(wait_seconds)
            except multiprocessing.TimeoutError as exc:
                raise SearchTimeout("搜索超时；可以增加超时时间或先检查色块识别是否准确。") from exc
            if status == "timeout":
                raise SearchTimeout("搜索超时；可以增加超时时间或先检查色块识别是否准确。")
            if result is not None:
                return result
        return None

    def _search_root_branch(
        self,
        cube: CubieCube,
        depth: int,
        move_idx: int,
        timeout_seconds: float | None,
    ) -> list[int] | None:
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        child = cube.apply_move_index(move_idx)
        tables = self.tables
        state = self._prepare_phase1_state(child, tables)
        *coords, heuristic = state
        return self._search_phase1(
            *coords,
            heuristic,
            depth - 1,
            MOVE_FACE_INDEX[move_idx],
            [move_idx],
            deadline,
            tables,
            {},
        )

    def _phase1_heuristic(
        self,
        tables: SolverTables,
        twist: int,
        flip: int,
        slice_comb: int,
        corner_perm: int,
    ) -> int:
        return max(
            tables.twist_slice_prune[twist * N_SLICE_COMB + slice_comb],
            tables.flip_slice_prune[flip * N_SLICE_COMB + slice_comb],
            tables.twist_flip_prune[twist * N_FLIP + flip],
            tables.corner_perm_prune[corner_perm],
        )

    def _phase2_heuristic(self, tables: SolverTables, cp: int, ep8: int, slice_perm: int) -> int:
        return max(
            tables.corner_slice_prune[cp * N_SLICE_PERM + slice_perm],
            tables.edge8_slice_prune[ep8 * N_SLICE_PERM + slice_perm],
        )

    def _search_phase1(
        self,
        twist: int,
        flip: int,
        slice_comb: int,
        corner_perm: int,
        edge_pack: int,
        x_twist: int,
        x_flip: int,
        x_slice: int,
        x_corner_perm: int,
        z_twist: int,
        z_flip: int,
        z_slice: int,
        z_corner_perm: int,
        heuristic: int,
        depth_left: int,
        last_face: int,
        path: list[int],
        deadline: float | None,
        tables: SolverTables,
        transposition: dict[int, int],
    ) -> list[int] | None:
        self._check_deadline(deadline)
        if heuristic > depth_left:
            return None

        key = _transposition_key(edge_pack, corner_perm, twist, flip, last_face)
        cached_depth = transposition.get(key)
        if cached_depth is not None and cached_depth >= depth_left:
            return None

        if twist == 0 and flip == 0 and slice_comb == tables.slice_solved:
            ep8 = perm_to_rank([(edge_pack >> (position * 4)) & 0xF for position in range(8)])
            slice_perm = perm_to_rank(
                [((edge_pack >> (position * 4)) & 0xF) - 8 for position in range(8, 12)]
            )
            phase2_result = self._search_phase2_from_coords(
                corner_perm,
                ep8,
                slice_perm,
                depth_left,
                last_face,
                path,
                deadline,
                tables,
            )
            if phase2_result is not None:
                return phase2_result

        if depth_left == 0:
            if len(transposition) < _TRANSPOSITION_LIMIT:
                transposition[key] = depth_left
            return None

        twist_move = tables.twist_move
        flip_move = tables.flip_move
        slice_move = tables.slice_comb_move
        corner_move = tables.corner_perm_all_move
        twist_slice_prune = tables.twist_slice_prune
        flip_slice_prune = tables.flip_slice_prune
        twist_flip_prune = tables.twist_flip_prune
        corner_prune = tables.corner_perm_prune
        x_move_map, z_move_map = _rotation_move_maps()
        next_depth = depth_left - 1

        # Collect children with their heuristics, then sort by heuristic ascending
        # so the most promising branches are explored first.
        children: list[tuple[int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int]] = []
        for move_idx, face in _ALLOWED_MOVES[last_face]:
            ntwist = twist_move[twist][move_idx]
            nflip = flip_move[flip][move_idx]
            nslice = slice_move[slice_comb][move_idx]
            ncorner_perm = corner_move[corner_perm][move_idx]
            child_heuristic = twist_slice_prune[ntwist * N_SLICE_COMB + nslice]
            value = flip_slice_prune[nflip * N_SLICE_COMB + nslice]
            if value > child_heuristic:
                child_heuristic = value
            value = twist_flip_prune[ntwist * N_FLIP + nflip]
            if value > child_heuristic:
                child_heuristic = value
            value = corner_prune[ncorner_perm]
            if value > child_heuristic:
                child_heuristic = value
            if child_heuristic > next_depth:
                continue

            x_move = x_move_map[move_idx]
            nx_twist = twist_move[x_twist][x_move]
            nx_flip = flip_move[x_flip][x_move]
            nx_slice = slice_move[x_slice][x_move]
            nx_corner_perm = corner_move[x_corner_perm][x_move]
            value = twist_slice_prune[nx_twist * N_SLICE_COMB + nx_slice]
            if value > child_heuristic:
                child_heuristic = value
            value = flip_slice_prune[nx_flip * N_SLICE_COMB + nx_slice]
            if value > child_heuristic:
                child_heuristic = value
            value = twist_flip_prune[nx_twist * N_FLIP + nx_flip]
            if value > child_heuristic:
                child_heuristic = value
            value = corner_prune[nx_corner_perm]
            if value > child_heuristic:
                child_heuristic = value
            if child_heuristic > next_depth:
                continue

            z_move = z_move_map[move_idx]
            nz_twist = twist_move[z_twist][z_move]
            nz_flip = flip_move[z_flip][z_move]
            nz_slice = slice_move[z_slice][z_move]
            nz_corner_perm = corner_move[z_corner_perm][z_move]
            value = twist_slice_prune[nz_twist * N_SLICE_COMB + nz_slice]
            if value > child_heuristic:
                child_heuristic = value
            value = flip_slice_prune[nz_flip * N_SLICE_COMB + nz_slice]
            if value > child_heuristic:
                child_heuristic = value
            value = twist_flip_prune[nz_twist * N_FLIP + nz_flip]
            if value > child_heuristic:
                child_heuristic = value
            value = corner_prune[nz_corner_perm]
            if value > child_heuristic:
                child_heuristic = value
            if child_heuristic > next_depth:
                continue

            next_edge_pack = _move_edge_pack(edge_pack, move_idx)
            children.append((
                child_heuristic, move_idx, face,
                ntwist, nflip, nslice, ncorner_perm, next_edge_pack,
                nx_twist, nx_flip, nx_slice, nx_corner_perm,
                nz_twist, nz_flip, nz_slice, nz_corner_perm,
            ))

        children.sort(key=lambda c: (c[0], c[1]))

        for child_data in children:
            child_heuristic = child_data[0]
            move_idx = child_data[1]
            face = child_data[2]
            ntwist, nflip, nslice, ncorner_perm = child_data[3:7]
            next_edge_pack = child_data[7]
            nx_twist, nx_flip, nx_slice, nx_corner_perm = child_data[8:12]
            nz_twist, nz_flip, nz_slice, nz_corner_perm = child_data[12:16]

            path.append(move_idx)
            result = self._search_phase1(
                ntwist,
                nflip,
                nslice,
                ncorner_perm,
                next_edge_pack,
                nx_twist,
                nx_flip,
                nx_slice,
                nx_corner_perm,
                nz_twist,
                nz_flip,
                nz_slice,
                nz_corner_perm,
                child_heuristic,
                next_depth,
                face,
                path,
                deadline,
                tables,
                transposition,
            )
            if result is not None:
                return result
            path.pop()

        if len(transposition) < _TRANSPOSITION_LIMIT:
            previous = transposition.get(key)
            if previous is None or depth_left > previous:
                transposition[key] = depth_left
        return None

    def _search_phase2_from_coords(
        self,
        cp: int,
        ep8: int,
        slice_perm: int,
        depth_left: int,
        last_face: int,
        path: list[int],
        deadline: float | None,
        tables: SolverTables,
    ) -> list[int] | None:
        heuristic = self._phase2_heuristic(tables, cp, ep8, slice_perm)
        return self._search_phase2(cp, ep8, slice_perm, heuristic, depth_left, last_face, path, deadline, tables)

    def _search_phase2(
        self,
        cp: int,
        ep8: int,
        slice_perm: int,
        heuristic: int,
        depth_left: int,
        last_face: int,
        path: list[int],
        deadline: float | None,
        tables: SolverTables,
    ) -> list[int] | None:
        self._check_deadline(deadline)
        if heuristic > depth_left:
            return None
        if cp == 0 and ep8 == 0 and slice_perm == 0:
            return path.copy()
        if depth_left == 0:
            return None

        next_depth = depth_left - 1
        for phase2_col, move_idx, face in _ALLOWED_PHASE2_MOVES[last_face]:
            ncp = tables.corner_perm_move[cp][phase2_col]
            nep8 = tables.edge8_perm_move[ep8][phase2_col]
            nslice = tables.slice_perm_move[slice_perm][phase2_col]
            child_heuristic = self._phase2_heuristic(tables, ncp, nep8, nslice)
            if child_heuristic > next_depth:
                continue

            path.append(move_idx)
            result = self._search_phase2(ncp, nep8, nslice, child_heuristic, next_depth, face, path, deadline, tables)
            if result is not None:
                return result
            path.pop()
        return None

    def _check_deadline(self, deadline: float | None) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise SearchTimeout("搜索超时；可以重试或先检查色块识别是否准确。")


def solve(facelets: str, max_depth: int = 20, timeout_seconds: float | None = 120.0) -> SolveResult:
    return OptimalSolver().solve_facelets(facelets, max_depth=max_depth, timeout_seconds=timeout_seconds)


def invert_moves(moves: list[str]) -> list[str]:
    result: list[str] = []
    for move in reversed(moves):
        if move.endswith("'"):
            result.append(move[0])
        elif move.endswith("2"):
            result.append(move)
        else:
            result.append(move + "'")
    return result


_SEARCH_WORKER_SOLVER: OptimalSolver | None = None


def _initialize_search_worker(cache_dir: str) -> None:
    global _SEARCH_WORKER_SOLVER
    _SEARCH_WORKER_SOLVER = OptimalSolver(cache_dir, parallel=False)
    _ = _SEARCH_WORKER_SOLVER.tables


def _search_worker_branch(
    task: tuple[CubieCube, int, int, float | None],
) -> tuple[str, list[int] | None]:
    cube, depth, move_idx, timeout_seconds = task
    if _SEARCH_WORKER_SOLVER is None:
        raise RuntimeError("Search worker was not initialized.")
    try:
        result = _SEARCH_WORKER_SOLVER._search_root_branch(
            cube,
            depth,
            move_idx,
            timeout_seconds,
        )
        return "ok", result
    except SearchTimeout:
        return "timeout", None
