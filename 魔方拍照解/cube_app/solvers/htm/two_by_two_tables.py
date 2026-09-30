"""Exact HTM distances for 7! * 3^6 corner states with DBL fixed."""

from __future__ import annotations

import hashlib
from pathlib import Path
import threading
import time
import uuid

import numpy as np

from .coords import perm_to_rank, rank_to_perm
from ...cubie import CubieCube, all_move_cubes

POSITIONS = (0, 1, 2, 3, 4, 5, 7)
LABELS = {position: label for label, position in enumerate(POSITIONS)}
MOVES = tuple(range(9))  # U, R, F do not move the fixed DBL corner.
PERMS = 5040
TWISTS = 729
ENTRIES = PERMS * TWISTS
CACHE_NAME = "two_by_two_htm_v1.bin"
MAGIC = b"T2HTM001"
_LOCK = threading.Lock()


def coordinates(cube: CubieCube) -> tuple[int, int]:
    if cube.cp[6] != 6 or cube.co[6] != 0:
        raise ValueError("DBL corner must be normalized before lookup")
    perm = perm_to_rank(tuple(LABELS[cube.cp[position]] for position in POSITIONS))
    twist = 0
    for position in POSITIONS[:-1]:
        twist = twist * 3 + cube.co[position]
    return perm, twist


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("二阶距离表初始化超时；可提前离线生成距离表。")


def _move_tables(deadline: float | None) -> tuple[np.ndarray, np.ndarray]:
    perm_moves = np.empty((PERMS, 9), dtype="<u2")
    twist_moves = np.empty((TWISTS, 9), dtype="<u2")
    for perm in range(PERMS):
        if perm % 256 == 0:
            _check_deadline(deadline)
        cp = list(range(8))
        for position, label in zip(POSITIONS, rank_to_perm(perm, 7)):
            cp[position] = POSITIONS[label]
        for move in MOVES:
            moved = tuple(cp[source] for source in all_move_cubes()[move].cp)
            perm_moves[perm, move] = perm_to_rank(tuple(LABELS[moved[position]] for position in POSITIONS))
    for twist in range(TWISTS):
        co = [0] * 8
        value = twist
        for position in reversed(POSITIONS[:-1]):
            co[position] = value % 3
            value //= 3
        co[7] = -sum(co) % 3
        for move in MOVES:
            action = all_move_cubes()[move]
            value = 0
            for position in POSITIONS[:-1]:
                value = value * 3 + (co[action.cp[position]] + action.co[position]) % 3
            twist_moves[twist, move] = value
    return perm_moves, twist_moves


def _build(deadline: float | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    perm_moves, twist_moves = _move_tables(deadline)
    distance = np.full(ENTRIES, 255, dtype=np.uint8)
    distance[0] = 0
    frontier = np.array([0], dtype=np.uint32)
    discovered = 1
    depth = 0
    while frontier.size:
        following = []
        for start in range(0, frontier.size, 131072):
            _check_deadline(deadline)
            part = frontier[start : start + 131072]
            perms, twists = part // TWISTS, part % TWISTS
            for move in MOVES:
                # Each fixed move is a bijection: a unique frontier yields unique children.
                children = perm_moves[perms, move].astype(np.uint32) * TWISTS + twist_moves[twists, move]
                unseen = children[distance[children] == 255]
                distance[unseen] = depth + 1
                if unseen.size:
                    following.append(unseen)
                    discovered += unseen.size
        frontier = np.concatenate(following) if following else np.empty(0, dtype=np.uint32)
        depth += 1
    if discovered != ENTRIES or int(distance.max()) != 11:
        raise RuntimeError("二阶全状态表未覆盖预期状态或直径错误")
    return distance, perm_moves, twist_moves


def _load(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = path.read_bytes()
    expected = ENTRIES + (PERMS + TWISTS) * 9 * 2
    if len(raw) != 40 + expected or raw[:8] != MAGIC or hashlib.sha256(raw[40:]).digest() != raw[8:40]:
        raise ValueError("invalid two-by-two cache")
    distance = np.frombuffer(raw, dtype=np.uint8, count=ENTRIES, offset=40)
    perm_moves = np.frombuffer(raw, dtype="<u2", count=PERMS * 9, offset=40 + ENTRIES).reshape(PERMS, 9)
    twist_moves = np.frombuffer(raw, dtype="<u2", count=TWISTS * 9, offset=40 + ENTRIES + PERMS * 9 * 2).reshape(
        TWISTS, 9
    )
    if distance[0] != 0 or int(distance.max()) != 11:
        raise ValueError("invalid two-by-two distances")
    return distance, perm_moves, twist_moves


def load_or_build(cache_directory: str, deadline: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    path = Path(cache_directory) / CACHE_NAME
    with _LOCK:
        _check_deadline(deadline)
        try:
            tables = _load(path)
        except (OSError, ValueError):
            tables = _build(deadline)
            data = b"".join(table.tobytes() for table in tables)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
                temporary.write_bytes(MAGIC + hashlib.sha256(data).digest() + data)
                temporary.replace(path)
            except OSError:
                # Read-only deployments can still use the verified in-memory table.
                pass
        _check_deadline(deadline)
        for table in tables:
            table.flags.writeable = False
        return tables


if __name__ == "__main__":
    import argparse
    from ...runtime import application_root

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=str(application_root() / ".cache"))
    args = parser.parse_args()
    started = time.monotonic()
    tables = load_or_build(args.cache_dir)
    print(f"{ENTRIES} states, diameter {int(tables[0].max())}, {time.monotonic() - started:.3f}s")
