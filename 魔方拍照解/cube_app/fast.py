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
from .cubie import CubieCube, MOVE_INDEX, MOVE_NAMES, from_facelets
from .metrics import MOVE_COSTS, normalize_metric, solution_cost
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
    """Find a feasible metric-aware two-phase solution without claiming optimality."""

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
        metric: str = "HTM",
    ) -> SolveResult:
        return self.solve_cube(from_facelets(facelets), timeout_seconds=timeout_seconds, metric=metric)

    def solve_cube(
        self,
        cube: CubieCube,
        timeout_seconds: float | None = 5.0,
        metric: str = "HTM",
    ) -> SolveResult:
        metric = normalize_metric(metric)
        prices = MOVE_COSTS[metric]
        phase1_limit = self.max_phase1_depth * (2 if metric == "QTM" else 1)
        phase2_limit = self.max_phase2_depth * (2 if metric == "QTM" else 1)
        started = time.monotonic()
        deadline = None if timeout_seconds is None else started + timeout_seconds
        if cube.is_solved():
            return SolveResult([], 0, metric, time.monotonic() - started, True)

        tables = self.tables
        twist = get_twist(cube)
        flip = get_flip(cube)
        slice_comb = get_slice_comb(cube)
        corner_perm = get_corner_perm(cube)
        edge_pack = _pack_edges(cube)
        lower = self._phase1_heuristic(tables, twist, flip, slice_comb)

        best: list[int] | None = None
        first_phase1_depth: int | None = None
        for phase1_depth in range(lower, phase1_limit + 1):
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
                prices,
                phase2_limit,
            )
            if best is not None:
                best = self._normalize_moves(best)
                first_phase1_depth = phase1_depth
                break

        if best is not None and deadline is not None and first_phase1_depth is not None:
            best_holder = [best]
            transposition: dict[int, int] = {}
            try:
                for phase1_depth in range(first_phase1_depth, phase1_limit + 1):
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
                        prices,
                        phase2_limit,
                    )
            except SearchTimeout:
                pass
            best = best_holder[0]

        if best is not None:
            best = self._normalize_moves(best)
            moves = [MOVE_NAMES[move_idx] for move_idx in best]
            verified = cube
            for move in moves:
                verified = verified.apply_move_index(MOVE_INDEX[move])
            if not verified.is_solved():
                raise RuntimeError("快速两阶段候选未复原原魔方。")
            return SolveResult(moves, solution_cost(moves, metric), metric, time.monotonic() - started, False)

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
        prices: tuple[int, ...],
        phase2_limit: int,
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
                remaining_limit = min(phase2_limit, sum(prices[move] for move in best_holder[0]) -
                                      sum(prices[move] for move in path) - 1)
                for phase2_depth in range(phase2_lower, remaining_limit + 1):
                    result = self._search_phase2(
                        corner_perm,
                        ep8,
                        slice_perm,
                        phase2_lower,
                        phase2_depth,
                        6,
                        path,
                        deadline,
                        tables,
                        prices,
                    )
                    if result is not None:
                        best_holder[0] = self._normalize_moves(result)
                        break
            if len(transposition) < 2_000_000:
                transposition[key] = depth_left
            return

        children: list[tuple[int, int, int, int, int, int, int, int, int]] = []
        for move_idx, face in _ALLOWED_MOVES[last_face]:
            next_depth = depth_left - prices[move_idx]
            if next_depth < 0:
                continue
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
                    next_depth,
                )
            )
        children.sort(key=lambda child: (child[0] + prices[child[1]], child[1]))

        for child in children:
            child_heuristic, move_idx, face, ntwist, nflip, nslice, ncorner, nedge_pack, next_depth = child
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
                prices,
                phase2_limit,
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
        prices: tuple[int, ...],
        phase2_limit: int,
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
            for phase2_depth in range(phase2_lower, phase2_limit + 1):
                result = self._search_phase2(
                    corner_perm,
                    ep8,
                    slice_perm,
                    phase2_lower,
                    phase2_depth,
                    6,
                    path,
                    deadline,
                    tables,
                    prices,
                )
                if result is not None:
                    return result
            return None

        twist_move = tables.twist_move
        flip_move = tables.flip_move
        slice_move = tables.slice_comb_move
        corner_move = tables.corner_perm_all_move
        for move_idx, face in _ALLOWED_MOVES[last_face]:
            next_depth = depth_left - prices[move_idx]
            if next_depth < 0:
                continue
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
                prices,
                phase2_limit,
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
        prices: tuple[int, ...],
    ) -> list[int] | None:
        self._check_deadline(deadline)
        if heuristic > depth_left:
            return None
        if cp == 0 and ep8 == 0 and slice_perm == 0:
            return path.copy()
        if depth_left == 0:
            return None

        for phase2_col, move_idx, face in _ALLOWED_PHASE2_MOVES[last_face]:
            next_depth = depth_left - prices[move_idx]
            if next_depth < 0:
                continue
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
                prices,
            )
            if result is not None:
                return result
            path.pop()
        return None

    @staticmethod
    def _normalize_moves(moves: list[int]) -> list[int]:
        result: list[int] = []
        for move in moves:
            if not result or result[-1] // 3 != move // 3:
                result.append(move)
                continue
            power = (result[-1] % 3 + 1 + move % 3 + 1) % 4
            result.pop()
            if power:
                result.append(move // 3 * 3 + power - 1)
        return result

    @staticmethod
    def _check_deadline(deadline: float | None) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise SearchTimeout("快速两阶段搜索超时。")
