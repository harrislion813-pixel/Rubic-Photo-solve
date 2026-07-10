from __future__ import annotations

import pickle
from array import array
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .coords import (
    N_CORNER_PERM,
    N_EDGE8_PERM,
    N_FLIP,
    N_SLICE_COMB,
    N_SLICE_PERM,
    N_TWIST,
    get_corner_perm,
    get_edge8_perm,
    get_flip,
    get_slice_comb,
    get_slice_perm,
    get_twist,
    set_corner_perm,
    set_edge8_perm,
    set_flip,
    set_slice_comb,
    set_slice_perm,
    set_twist,
)
from .cubie import CubieCube, PHASE2_MOVES, all_move_cubes


CACHE_VERSION = 3


@dataclass(slots=True)
class SolverTables:
    twist_move: tuple[array, ...]
    flip_move: tuple[array, ...]
    slice_comb_move: tuple[array, ...]
    corner_perm_all_move: tuple[array, ...]
    corner_perm_move: tuple[array, ...]
    edge8_perm_move: tuple[array, ...]
    slice_perm_move: tuple[array, ...]
    twist_flip_prune: bytearray
    corner_perm_prune: bytearray
    twist_slice_prune: bytearray
    flip_slice_prune: bytearray
    corner_slice_prune: bytearray
    edge8_slice_prune: bytearray
    slice_solved: int


def load_or_build_tables(cache_dir: str | Path = ".cache") -> SolverTables:
    cache_path = Path(cache_dir) / f"solver_tables_v{CACHE_VERSION}.pkl"
    if cache_path.exists():
        with cache_path.open("rb") as handle:
            payload = pickle.load(handle)
        if payload.get("version") == CACHE_VERSION:
            return payload["tables"]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tables = build_tables()
    with cache_path.open("wb") as handle:
        pickle.dump({"version": CACHE_VERSION, "tables": tables}, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return tables


def build_tables() -> SolverTables:
    twist_move = build_move_table(N_TWIST, set_twist, get_twist, range(18))
    flip_move = build_move_table(N_FLIP, set_flip, get_flip, range(18))
    slice_comb_move = build_move_table(N_SLICE_COMB, set_slice_comb, get_slice_comb, range(18))
    corner_perm_all_move = build_move_table(N_CORNER_PERM, set_corner_perm, get_corner_perm, range(18))

    corner_perm_move = build_move_table(N_CORNER_PERM, set_corner_perm, get_corner_perm, PHASE2_MOVES)
    edge8_perm_move = build_move_table(N_EDGE8_PERM, set_edge8_perm, get_edge8_perm, PHASE2_MOVES)
    slice_perm_move = build_move_table(N_SLICE_PERM, set_slice_perm, get_slice_perm, PHASE2_MOVES)

    slice_solved = get_slice_comb(CubieCube())
    twist_slice_prune = build_pair_prune(
        N_TWIST,
        N_SLICE_COMB,
        0,
        slice_solved,
        twist_move,
        slice_comb_move,
    )
    flip_slice_prune = build_pair_prune(
        N_FLIP,
        N_SLICE_COMB,
        0,
        slice_solved,
        flip_move,
        slice_comb_move,
    )
    twist_flip_prune = build_pair_prune(
        N_TWIST,
        N_FLIP,
        0,
        0,
        twist_move,
        flip_move,
    )
    corner_perm_prune = build_single_prune(N_CORNER_PERM, 0, corner_perm_all_move)
    corner_slice_prune = build_pair_prune(
        N_CORNER_PERM,
        N_SLICE_PERM,
        0,
        0,
        corner_perm_move,
        slice_perm_move,
    )
    edge8_slice_prune = build_pair_prune(
        N_EDGE8_PERM,
        N_SLICE_PERM,
        0,
        0,
        edge8_perm_move,
        slice_perm_move,
    )

    return SolverTables(
        twist_move=twist_move,
        flip_move=flip_move,
        slice_comb_move=slice_comb_move,
        corner_perm_all_move=corner_perm_all_move,
        corner_perm_move=corner_perm_move,
        edge8_perm_move=edge8_perm_move,
        slice_perm_move=slice_perm_move,
        twist_flip_prune=twist_flip_prune,
        corner_perm_prune=corner_perm_prune,
        twist_slice_prune=twist_slice_prune,
        flip_slice_prune=flip_slice_prune,
        corner_slice_prune=corner_slice_prune,
        edge8_slice_prune=edge8_slice_prune,
        slice_solved=slice_solved,
    )


def build_move_table(
    size: int,
    setter: Callable[[int], CubieCube],
    getter: Callable[[CubieCube], int],
    moves: range | tuple[int, ...],
) -> tuple[array, ...]:
    move_cubes = all_move_cubes()
    rows: list[array] = []
    typecode = "H" if size <= 65535 else "I"
    for coord in range(size):
        cube = setter(coord)
        rows.append(array(typecode, (getter(cube.moved(move_cubes[move_idx])) for move_idx in moves)))
    return tuple(rows)


def build_pair_prune(
    size_a: int,
    size_b: int,
    solved_a: int,
    solved_b: int,
    move_a: tuple[array, ...],
    move_b: tuple[array, ...],
) -> bytearray:
    table = bytearray([255]) * (size_a * size_b)
    start = solved_a * size_b + solved_b
    table[start] = 0
    queue: deque[int] = deque([start])
    move_count = len(move_a[0])

    while queue:
        idx = queue.popleft()
        a, b = divmod(idx, size_b)
        depth = table[idx] + 1
        for move_idx in range(move_count):
            na = move_a[a][move_idx]
            nb = move_b[b][move_idx]
            nidx = na * size_b + nb
            if table[nidx] == 255:
                table[nidx] = depth
                queue.append(nidx)
    return table


def build_single_prune(
    size: int,
    solved: int,
    move_table: tuple[array, ...],
) -> bytearray:
    table = bytearray([255]) * size
    table[solved] = 0
    queue: deque[int] = deque([solved])
    move_count = len(move_table[0])

    while queue:
        coord = queue.popleft()
        depth = table[coord] + 1
        for move_idx in range(move_count):
            next_coord = move_table[coord][move_idx]
            if table[next_coord] == 255:
                table[next_coord] = depth
                queue.append(next_coord)
    return table
