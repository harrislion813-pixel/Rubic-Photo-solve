from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import time
import threading
from pathlib import Path

from ...runtime import application_root
from .two_by_two_tables import coordinates, load_or_build
from ...metrics import move_cost, normalize_metric, resolve_max_depth, solution_cost
from ...cubie import (
    CORNER_COLORS,
    MOVE_INDEX,
    MOVE_NAMES,
    CubeStateError,
    CubieCube,
    all_move_cubes,
)


# For each 3x3 corner-facelet index, the corresponding index in a compact
# U,R,F,D,L,B / TL,TR,BL,BR 2x2 facelet string.
_CORNER_FACELET_2 = (
    (3, 4, 9),  # URF
    (2, 8, 17),  # UFL
    (0, 16, 21),  # ULB
    (1, 20, 5),  # UBR
    (13, 11, 6),  # DFR
    (12, 19, 10),  # DLF
    (14, 23, 18),  # DBL
    (15, 7, 22),  # DRB
)

_ROTATION_GENERATORS = (
    (MOVE_INDEX["R"], MOVE_INDEX["L'"]),
    (MOVE_INDEX["U"], MOVE_INDEX["D'"]),
    (MOVE_INDEX["F"], MOVE_INDEX["B'"]),
)


@dataclass(frozen=True, slots=True)
class TwoByTwoResult:
    moves: list[str]
    depth: int
    metric: str
    elapsed_seconds: float
    optimal: bool = True

    @property
    def text(self) -> str:
        return " ".join(self.moves)


def clean_facelets_2x2(facelets: str) -> str:
    compact = "".join(ch for ch in facelets.upper() if ch in "URFDLB")
    if len(compact) != 24:
        raise CubeStateError("二阶魔方需要 24 个面贴字符，顺序为 U R F D L B。")
    wrong = {face: compact.count(face) for face in "URFDLB" if compact.count(face) != 4}
    if wrong:
        detail = "，".join(f"{face}={count}" for face, count in wrong.items())
        raise CubeStateError(f"二阶每种颜色必须正好 4 个，当前数量异常：{detail}")
    return compact


def from_facelets_2x2(facelets: str) -> CubieCube:
    f = clean_facelets_2x2(facelets)
    cp = [-1] * 8
    co = [-1] * 8
    for pos, indices in enumerate(_CORNER_FACELET_2):
        ori = next((candidate for candidate in range(3) if f[indices[candidate]] in "UD"), None)
        if ori is None:
            raise CubeStateError(f"二阶角块位置 {pos + 1} 缺少 U/D 色；请检查配色或照片方向。")
        color1 = f[indices[(ori + 1) % 3]]
        color2 = f[indices[(ori + 2) % 3]]
        for cubie, colors in enumerate(CORNER_COLORS):
            if colors[1] == color1 and colors[2] == color2:
                cp[pos] = cubie
                co[pos] = ori
                break
        if cp[pos] < 0:
            colors = "/".join(f[index] for index in indices)
            raise CubeStateError(f"无法识别二阶角块位置 {pos + 1} 的颜色组合（{colors}）。")

    if sorted(cp) != list(range(8)):
        raise CubeStateError("二阶角块集合不完整或有重复；请检查颜色识别和六面方向。")
    if sum(co) % 3:
        raise CubeStateError("二阶角块朝向不合法；请旋转照片或手动校正色块。")
    return CubieCube(cp=tuple(cp), co=tuple(co))


def to_facelets_2x2(cube: CubieCube) -> str:
    facelets = ["?"] * 24
    for pos, indices in enumerate(_CORNER_FACELET_2):
        cubie = cube.cp[pos]
        ori = cube.co[pos]
        for n in range(3):
            facelets[indices[(n + ori) % 3]] = CORNER_COLORS[cubie][n]
    return "".join(facelets)


def _corner_moved(cube: CubieCube, move_index: int) -> CubieCube:
    move = all_move_cubes()[move_index]
    cp = tuple(cube.cp[move.cp[pos]] for pos in range(8))
    co = tuple((cube.co[move.cp[pos]] + move.co[pos]) % 3 for pos in range(8))
    return CubieCube(cp=cp, co=co)


@lru_cache(maxsize=1)
def rotated_solved_corners() -> frozenset[tuple[tuple[int, ...], tuple[int, ...]]]:
    solved = CubieCube()
    queue = deque([solved])
    seen = {(solved.cp, solved.co)}
    while queue:
        cube = queue.popleft()
        for first, second in _ROTATION_GENERATORS:
            rotated = _corner_moved(_corner_moved(cube, first), second)
            key = (rotated.cp, rotated.co)
            if key not in seen:
                seen.add(key)
                queue.append(rotated)
    if len(seen) != 24:
        raise RuntimeError(f"Expected 24 cube orientations, got {len(seen)}")
    return frozenset(seen)


def is_solved_2x2(cube: CubieCube) -> bool:
    return (cube.cp, cube.co) in rotated_solved_corners()


@lru_cache(maxsize=1)
def _normalizations() -> tuple[tuple[CubieCube, tuple[int, ...]], ...]:
    rotations = [CubieCube(cp=cp, co=co) for cp, co in sorted(rotated_solved_corners())]
    move_keys = {(move.cp, move.co): index for index, move in enumerate(all_move_cubes())}
    result = []
    for rotation in rotations:
        inverse = next(
            candidate
            for candidate in rotations
            if rotation.moved(candidate).cp == tuple(range(8)) and rotation.moved(candidate).co == (0,) * 8
        )
        mapped = []
        for move in all_move_cubes()[:9]:
            action = rotation.moved(move).moved(inverse)
            mapped.append(move_keys[(action.cp, action.co)])
        result.append((rotation, tuple(mapped)))
    return tuple(result)


class TwoByTwoSolver:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else application_root() / ".cache"
        self._tables = {}

    def solve_facelets(
        self, facelets: str, max_depth: int | None = None, timeout_seconds: float | None = 10.0,
        metric: str = "HTM", cancel_event: threading.Event | None = None,
    ) -> TwoByTwoResult:
        return self.solve_cube(
            from_facelets_2x2(facelets), max_depth=max_depth, timeout_seconds=timeout_seconds,
            metric=metric, cancel_event=cancel_event,
        )

    def solve_cube(
        self, cube: CubieCube, max_depth: int | None = None, timeout_seconds: float | None = 10.0,
        metric: str = "HTM", cancel_event: threading.Event | None = None,
    ) -> TwoByTwoResult:
        metric = normalize_metric(metric)
        max_depth = resolve_max_depth(2, metric, max_depth)
        started = time.monotonic()
        deadline = None if timeout_seconds is None else started + timeout_seconds
        if is_solved_2x2(cube):
            return TwoByTwoResult([], 0, metric, time.monotonic() - started)
        if metric not in self._tables:
            self._tables[metric] = load_or_build(str(self.cache_dir), deadline, metric)
        if cancel_event is not None and cancel_event.is_set():
            raise TimeoutError("QTM 二阶搜索已让出资源。")
        distance, perm_moves, twist_moves = self._tables[metric]
        for rotation, move_map in _normalizations():
            normalized = cube.moved(rotation)
            if normalized.cp[6] == 6 and normalized.co[6] == 0:
                break
        else:
            raise CubeStateError("二阶角块状态无法规范化。")
        perm, twist = coordinates(normalized)
        depth = int(distance[perm * 729 + twist])
        if depth > max_depth:
            raise ValueError(f"二阶 {metric} 搜索预算 {max_depth} 步不足；准确最短长度为 {depth} 步。")
        path = []
        remaining = depth
        # Prefer a compact half-turn token when its weighted edge is shortest.
        path_moves = (1, 4, 7, 0, 2, 3, 5, 6, 8) if metric == "QTM" else range(9)
        while remaining:
            if cancel_event is not None and cancel_event.is_set():
                raise TimeoutError("QTM 二阶搜索已让出资源。")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("二阶最短解搜索超时。")
            for move in path_moves:
                next_perm = int(perm_moves[perm, move])
                next_twist = int(twist_moves[twist, move])
                cost = move_cost(move, metric)
                if int(distance[next_perm * 729 + next_twist]) + cost == remaining:
                    path.append(MOVE_NAMES[move_map[move]])
                    perm, twist = next_perm, next_twist
                    remaining -= cost
                    break
            else:
                raise RuntimeError("二阶距离表缺少递减路径。")
        verified = cube
        for name in path:
            verified = _corner_moved(verified, MOVE_INDEX[name])
        if not is_solved_2x2(verified) or solution_cost(path, metric) != depth:
            raise RuntimeError("二阶动作映射未通过复原验证。")
        return TwoByTwoResult(path, depth, metric, time.monotonic() - started)
