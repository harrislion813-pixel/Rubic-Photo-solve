from __future__ import annotations

import time
from pathlib import Path

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
from .cubie import CubieCube, MOVE_NAMES, from_facelets
from .optimal import (
    SolveResult,
    SearchTimeout,
    _ALLOWED_MOVES,
    _ALLOWED_PHASE2_MOVES,
    _move_edge_pack,
    _pack_edges,
    _transposition_key,
)
from .tables import SolverTables, load_or_build_tables


class FastTwoPhaseSolver:
    """Find a short HTM solution quickly without claiming optimality."""

    def __init__(
        self,
        cache_dir: str | Path = ".cache",
        *,
        tables: SolverTables | None = None,
        max_phase1_depth: int = 12,
        max_phase2_depth: int = 14,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self._tables = tables
        self.max_phase1_depth = max_phase1_depth
        self.max_phase2_depth = max_phase2_depth

    @property
    def tables(self) -> SolverTables:
        if self._tables is None:
            self._tables = load_or_build_tables(self.cache_dir)
        return self._tables

    def solve_facelets(
        self,
        facelets: str,
        timeout_seconds: float | None = 5.0,
    ) -> SolveResult:
        return self.solve_cube(from_facelets(facelets), timeout_seconds=timeout_seconds)

    def solve_cube(
        self,
        cube: CubieCube,
        timeout_seconds: float | None = 5.0,
    ) -> SolveResult:
        started = time.monotonic()
        deadline = None if timeout_seconds is None else started + timeout_seconds
        if cube.is_solved():
            return SolveResult([], 0, "HTM", time.monotonic() - started, True)

        tables = self.tables
        twist = get_twist(cube)
        flip = get_flip(cube)
        slice_comb = get_slice_comb(cube)
        corner_perm = get_corner_perm(cube)
        edge_pack = _pack_edges(cube)
        lower = self._phase1_heuristic(tables, twist, flip, slice_comb)

        best: list[int] | None = None
        first_phase1_depth: int | None = None
        for phase1_depth in range(lower, self.max_phase1_depth + 1):
            best = self._search_phase1(
                twist,
                flip,
                slice_comb,
                corner_perm,
                edge_pack,
                lower,
                phase1_depth,
                6,
                [],
                deadline,
                tables,
            )
            if best is not None:
                first_phase1_depth = phase1_depth
                break

        if best is not None and deadline is not None and first_phase1_depth is not None:
            best_holder = [best]
            transposition: dict[int, int] = {}
            try:
                for phase1_depth in range(first_phase1_depth, self.max_phase1_depth + 1):
                    self._improve_phase1(
                        twist,
                        flip,
                        slice_comb,
                        corner_perm,
                        edge_pack,
                        lower,
                        phase1_depth,
                        6,
                        [],
                        deadline,
                        tables,
                        best_holder,
                        transposition,
                    )
            except SearchTimeout:
                pass
            best = best_holder[0]

        if best is not None:
            moves = [MOVE_NAMES[move_idx] for move_idx in best]
            return SolveResult(moves, len(moves), "HTM", time.monotonic() - started, False)

        raise SearchTimeout("快速两阶段搜索未在限制内找到解法；严格搜索仍可继续。")

    def _improve_phase1(
        self,
        twist: int,
        flip: int,
        slice_comb: int,
        corner_perm: int,
        edge_pack: int,
        heuristic: int,
        depth_left: int,
        last_face: int,
        path: list[int],
        deadline: float,
        tables: SolverTables,
        best_holder: list[list[int]],
        transposition: dict[int, int],
    ) -> None:
        self._check_deadline(deadline)
        if heuristic > depth_left:
            return

        key = _transposition_key(edge_pack, corner_perm, twist, flip, last_face)
        cached_depth = transposition.get(key)
        if cached_depth is not None and cached_depth >= depth_left:
            return

        if depth_left == 0:
            if twist == 0 and flip == 0 and slice_comb == tables.slice_solved:
                ep8 = perm_to_rank([(edge_pack >> (position * 4)) & 0xF for position in range(8)])
                slice_perm = perm_to_rank(
                    [((edge_pack >> (position * 4)) & 0xF) - 8 for position in range(8, 12)]
                )
                phase2_lower = self._phase2_heuristic(tables, corner_perm, ep8, slice_perm)
                phase2_limit = min(self.max_phase2_depth, len(best_holder[0]) - len(path) - 1)
                for phase2_depth in range(phase2_lower, phase2_limit + 1):
                    result = self._search_phase2(
                        corner_perm,
                        ep8,
                        slice_perm,
                        phase2_lower,
                        phase2_depth,
                        last_face,
                        path,
                        deadline,
                        tables,
                    )
                    if result is not None:
                        best_holder[0] = result
                        break
            if len(transposition) < 2_000_000:
                transposition[key] = depth_left
            return

        next_depth = depth_left - 1
        children: list[tuple[int, int, int, int, int, int, int, int]] = []
        for move_idx, face in _ALLOWED_MOVES[last_face]:
            ntwist = tables.twist_move[twist][move_idx]
            nflip = tables.flip_move[flip][move_idx]
            nslice = tables.slice_comb_move[slice_comb][move_idx]
            child_heuristic = self._phase1_heuristic(tables, ntwist, nflip, nslice)
            if child_heuristic > next_depth:
                continue
            children.append(
                (
                    child_heuristic,
                    move_idx,
                    face,
                    ntwist,
                    nflip,
                    nslice,
                    tables.corner_perm_all_move[corner_perm][move_idx],
                    _move_edge_pack(edge_pack, move_idx),
                )
            )
        children.sort(key=lambda child: (child[0], child[1]))

        for child in children:
            child_heuristic, move_idx, face, ntwist, nflip, nslice, ncorner, nedge_pack = child
            path.append(move_idx)
            self._improve_phase1(
                ntwist,
                nflip,
                nslice,
                ncorner,
                nedge_pack,
                child_heuristic,
                next_depth,
                face,
                path,
                deadline,
                tables,
                best_holder,
                transposition,
            )
            path.pop()

        if len(transposition) < 2_000_000:
            previous = transposition.get(key)
            if previous is None or depth_left > previous:
                transposition[key] = depth_left

    @staticmethod
    def _phase1_heuristic(tables: SolverTables, twist: int, flip: int, slice_comb: int) -> int:
        return max(
            tables.twist_slice_prune[twist * N_SLICE_COMB + slice_comb],
            tables.flip_slice_prune[flip * N_SLICE_COMB + slice_comb],
            tables.twist_flip_prune[twist * N_FLIP + flip],
        )

    @staticmethod
    def _phase2_heuristic(tables: SolverTables, cp: int, ep8: int, slice_perm: int) -> int:
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
        if depth_left == 0:
            if twist != 0 or flip != 0 or slice_comb != tables.slice_solved:
                return None
            ep8 = perm_to_rank([(edge_pack >> (position * 4)) & 0xF for position in range(8)])
            slice_perm = perm_to_rank(
                [((edge_pack >> (position * 4)) & 0xF) - 8 for position in range(8, 12)]
            )
            phase2_lower = self._phase2_heuristic(tables, corner_perm, ep8, slice_perm)
            for phase2_depth in range(phase2_lower, self.max_phase2_depth + 1):
                result = self._search_phase2(
                    corner_perm,
                    ep8,
                    slice_perm,
                    phase2_lower,
                    phase2_depth,
                    last_face,
                    path,
                    deadline,
                    tables,
                )
                if result is not None:
                    return result
            return None

        twist_move = tables.twist_move
        flip_move = tables.flip_move
        slice_move = tables.slice_comb_move
        corner_move = tables.corner_perm_all_move
        next_depth = depth_left - 1
        for move_idx, face in _ALLOWED_MOVES[last_face]:
            ntwist = twist_move[twist][move_idx]
            nflip = flip_move[flip][move_idx]
            nslice = slice_move[slice_comb][move_idx]
            child_heuristic = self._phase1_heuristic(tables, ntwist, nflip, nslice)
            if child_heuristic > next_depth:
                continue

            path.append(move_idx)
            result = self._search_phase1(
                ntwist,
                nflip,
                nslice,
                corner_move[corner_perm][move_idx],
                _move_edge_pack(edge_pack, move_idx),
                child_heuristic,
                next_depth,
                face,
                path,
                deadline,
                tables,
            )
            if result is not None:
                return result
            path.pop()
        return None

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
            result = self._search_phase2(
                ncp,
                nep8,
                nslice,
                child_heuristic,
                next_depth,
                face,
                path,
                deadline,
                tables,
            )
            if result is not None:
                return result
            path.pop()
        return None

    @staticmethod
    def _check_deadline(deadline: float | None) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise SearchTimeout("快速两阶段搜索超时。")
