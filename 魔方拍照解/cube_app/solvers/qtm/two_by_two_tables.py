"""Exact HTM/QTM distances for 7! * 3^6 corner states with DBL fixed."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
import threading
import time
import uuid

import numpy as np

from .coords import perm_to_rank, rank_to_perm
from ...cubie import CubieCube, all_move_cubes
from ...metrics import normalize_metric

POSITIONS = (0, 1, 2, 3, 4, 5, 7)
LABELS = {position: label for label, position in enumerate(POSITIONS)}
MOVES = tuple(range(9))  # U, R, F do not move the fixed DBL corner.
PERMS = 5040
TWISTS = 729
ENTRIES = PERMS * TWISTS
CACHE_NAME = "two_by_two_htm_v1.bin"
MAGIC = b"T2HTM001"
CACHE_NAMES = {"HTM": CACHE_NAME, "QTM": "two_by_two_qtm_v1.bin"}
MAGICS = {"HTM": MAGIC, "QTM": b"T2QTM001"}
DIAMETERS = {"HTM": 11, "QTM": 14}
QTM_MOVES = (0, 2, 3, 5, 6, 8)
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


@contextmanager
def _table_lock(deadline: float | None):
    if deadline is None:
        _LOCK.acquire()
    else:
        while True:
            _check_deadline(deadline)
            if _LOCK.acquire(timeout=min(0.05, max(0.0, deadline - time.monotonic()))):
                break
    try:
        _check_deadline(deadline)
        yield
    finally:
        _LOCK.release()


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


def _build(deadline: float | None, metric: str = "HTM") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    metric = normalize_metric(metric)
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
            # QTM uses six unit-cost edges. Consecutive same-face edges are
            # essential here (e.g. R R), so only the visited states prune BFS.
            for move in MOVES if metric == "HTM" else QTM_MOVES:
                # Each fixed move is a bijection: a unique frontier yields unique children.
                children = perm_moves[perms, move].astype(np.uint32) * TWISTS + twist_moves[twists, move]
                unseen = children[distance[children] == 255]
                distance[unseen] = depth + 1
                if unseen.size:
                    following.append(unseen)
                    discovered += unseen.size
        frontier = np.concatenate(following) if following else np.empty(0, dtype=np.uint32)
        depth += 1
    if discovered != ENTRIES or int(distance.max()) != DIAMETERS[metric]:
        raise RuntimeError("二阶全状态表未覆盖预期状态或直径错误")
    return distance, perm_moves, twist_moves


def _load(path: Path, metric: str = "HTM") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    metric = normalize_metric(metric)
    raw = path.read_bytes()
    expected = ENTRIES + (PERMS + TWISTS) * 9 * 2
    if len(raw) != 40 + expected or raw[:8] != MAGICS[metric] or hashlib.sha256(raw[40:]).digest() != raw[8:40]:
        raise ValueError("invalid two-by-two cache")
    distance = np.frombuffer(raw, dtype=np.uint8, count=ENTRIES, offset=40)
    perm_moves = np.frombuffer(raw, dtype="<u2", count=PERMS * 9, offset=40 + ENTRIES).reshape(PERMS, 9)
    twist_moves = np.frombuffer(raw, dtype="<u2", count=TWISTS * 9, offset=40 + ENTRIES + PERMS * 9 * 2).reshape(
        TWISTS, 9
    )
    if distance[0] != 0 or int(distance.max()) != DIAMETERS[metric]:
        raise ValueError("invalid two-by-two distances")
    return distance, perm_moves, twist_moves


def load_or_build(
    cache_directory: str, deadline: float | None = None, metric: str = "HTM"
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    metric = normalize_metric(metric)
    path = Path(cache_directory) / CACHE_NAMES[metric]
    with _table_lock(deadline):
        _check_deadline(deadline)
        try:
            tables = _load(path, metric)
        except (OSError, ValueError):
            tables = _build(deadline, metric)
            data = b"".join(table.tobytes() for table in tables)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
                temporary.write_bytes(MAGICS[metric] + hashlib.sha256(data).digest() + data)
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
    parser.add_argument("--metric", choices=("HTM", "QTM"), default="HTM", type=str.upper)
    args = parser.parse_args()
    started = time.monotonic()
    tables = load_or_build(args.cache_dir, metric=args.metric)
    print(f"{args.metric}: {ENTRIES} states, diameter {int(tables[0].max())}, {time.monotonic() - started:.3f}s")
