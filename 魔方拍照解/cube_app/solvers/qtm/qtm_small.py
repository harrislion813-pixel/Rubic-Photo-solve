"""Complete quarter-turn pruning tables for the Python strict fallback."""

from __future__ import annotations

import hashlib
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import struct

from .coords import N_CORNER_PERM, N_FLIP, N_SLICE_COMB, N_TWIST
from .tables import SolverTables, load_or_build_tables


MAGIC = b"QSMALL01"
QUARTER_MOVES = tuple(move for move in range(18) if move % 3 != 1)
LENGTHS = (N_TWIST * N_SLICE_COMB, N_FLIP * N_SLICE_COMB, N_TWIST * N_FLIP, N_CORNER_PERM)
HEADER = struct.Struct("<8s4I32s")
FILENAME = "qtm_small_v1.bin"


@dataclass(slots=True)
class QtmSmallTables:
    twist_slice: bytearray
    flip_slice: bytearray
    twist_flip: bytearray
    corner_perm: bytearray

    def parts(self) -> tuple[bytearray, ...]:
        return self.twist_slice, self.flip_slice, self.twist_flip, self.corner_perm


def _pair(size_a: int, size_b: int, goal_b: int, move_a: tuple, move_b: tuple) -> bytearray:
    table = bytearray([255]) * (size_a * size_b)
    goal = goal_b
    table[goal] = 0
    queue: deque[int] = deque([goal])
    while queue:
        index = queue.popleft()
        a, b = divmod(index, size_b)
        distance = table[index] + 1
        row_a, row_b = move_a[a], move_b[b]
        for move in QUARTER_MOVES:
            child = row_a[move] * size_b + row_b[move]
            if table[child] == 255:
                table[child] = distance
                queue.append(child)
    if 255 in table:
        raise RuntimeError("QTM pair pruning table did not cover its coordinate space")
    return table


def _corner(move_table: tuple) -> bytearray:
    table = bytearray([255]) * N_CORNER_PERM
    table[0] = 0
    queue: deque[int] = deque([0])
    while queue:
        index = queue.popleft()
        distance = table[index] + 1
        for move in QUARTER_MOVES:
            child = move_table[index][move]
            if table[child] == 255:
                table[child] = distance
                queue.append(child)
    if 255 in table:
        raise RuntimeError("QTM corner pruning table did not cover its coordinate space")
    return table


def build_qtm_small_tables(tables: SolverTables) -> QtmSmallTables:
    return QtmSmallTables(
        _pair(N_TWIST, N_SLICE_COMB, tables.slice_solved, tables.twist_move, tables.slice_comb_move),
        _pair(N_FLIP, N_SLICE_COMB, tables.slice_solved, tables.flip_move, tables.slice_comb_move),
        _pair(N_TWIST, N_FLIP, 0, tables.twist_move, tables.flip_move),
        _corner(tables.corner_perm_all_move),
    )


def load_qtm_small_tables(cache_dir: str | Path = ".cache") -> QtmSmallTables | None:
    path = Path(cache_dir) / FILENAME
    try:
        with path.open("rb") as source:
            header = source.read(HEADER.size)
            if len(header) != HEADER.size:
                return None
            magic, *fields = HEADER.unpack(header)
            *lengths, expected_digest = fields
            if magic != MAGIC or tuple(lengths) != LENGTHS:
                return None
            data = source.read(sum(LENGTHS))
            if len(data) != sum(LENGTHS) or source.read(1) or hashlib.sha256(data).digest() != expected_digest:
                return None
    except OSError:
        return None
    parts = []
    offset = 0
    for length in LENGTHS:
        part = bytearray(data[offset:offset + length])
        if 255 in part:
            return None
        parts.append(part)
        offset += length
    return QtmSmallTables(*parts)


def save_qtm_small_tables(tables: QtmSmallTables, cache_dir: str | Path = ".cache") -> Path:
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / FILENAME
    data = b"".join(tables.parts())
    if tuple(len(part) for part in tables.parts()) != LENGTHS or any(255 in part for part in tables.parts()):
        raise ValueError("QTM small tables are incomplete")
    header = HEADER.pack(MAGIC, *LENGTHS, hashlib.sha256(data).digest())
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as target:
            target.write(header)
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def main() -> None:
    tables = load_or_build_tables()
    target = save_qtm_small_tables(build_qtm_small_tables(tables))
    print(f"QTM small tables: {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
