from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import time

from .coords import N_CORNER_PERM, N_TWIST, get_corner_perm, get_twist, set_corner_perm, set_twist
from .cubie import (
    CORNER_COLORS,
    MOVE_FACE_INDEX,
    MOVE_INDEX,
    MOVE_NAMES,
    CubeStateError,
    CubieCube,
    all_move_cubes,
    should_skip_move,
)


# For each 3x3 corner-facelet index, the corresponding index in a compact
# U,R,F,D,L,B / TL,TR,BL,BR 2x2 facelet string.
_CORNER_FACELET_2 = (
    (3, 4, 9),    # URF
    (2, 8, 17),   # UFL
    (0, 16, 21),  # ULB
    (1, 20, 5),   # UBR
    (13, 11, 6),  # DFR
    (12, 19, 10), # DLF
    (14, 23, 18), # DBL
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
def _tables() -> tuple[tuple[array, ...], tuple[array, ...], bytearray, bytearray, frozenset[tuple[int, int]]]:
    # Build as lists first: assigning into many tiny arrays is measurably slower.
    twist_rows: list[array] = []
    for coord in range(N_TWIST):
        cube = set_twist(coord)
        twist_rows.append(array("H", (get_twist(_corner_moved(cube, move)) for move in range(18))))
    perm_rows: list[array] = []
    for coord in range(N_CORNER_PERM):
        cube = set_corner_perm(coord)
        perm_rows.append(array("H", (get_corner_perm(_corner_moved(cube, move)) for move in range(18))))

    goals = rotated_solved_corners()
    goal_coords = frozenset((get_twist(CubieCube(co=co)), get_corner_perm(CubieCube(cp=cp))) for cp, co in goals)
    twist_distance = _multi_source_distances(twist_rows, {twist for twist, _ in goal_coords})
    perm_distance = _multi_source_distances(perm_rows, {perm for _, perm in goal_coords})
    return tuple(twist_rows), tuple(perm_rows), twist_distance, perm_distance, goal_coords


def _multi_source_distances(move_table: list[array], goals: set[int]) -> bytearray:
    unseen = 255
    distance = bytearray([unseen]) * len(move_table)
    queue = deque(goals)
    for goal in goals:
        distance[goal] = 0
    while queue:
        state = queue.popleft()
        next_depth = distance[state] + 1
        for child in move_table[state]:
            if distance[child] == unseen:
                distance[child] = next_depth
                queue.append(child)
    return distance


class TwoByTwoSolver:
    def solve_facelets(self, facelets: str, max_depth: int = 11, timeout_seconds: float | None = 10.0) -> TwoByTwoResult:
        return self.solve_cube(from_facelets_2x2(facelets), max_depth=max_depth, timeout_seconds=timeout_seconds)

    def solve_cube(self, cube: CubieCube, max_depth: int = 11, timeout_seconds: float | None = 10.0) -> TwoByTwoResult:
        started = time.monotonic()
        if is_solved_2x2(cube):
            return TwoByTwoResult([], 0, "HTM", time.monotonic() - started)
        twist_moves, perm_moves, twist_distance, perm_distance, goals = _tables()
        twist = get_twist(cube)
        perm = get_corner_perm(cube)
        lower = max(twist_distance[twist], perm_distance[perm])
        deadline = None if timeout_seconds is None else started + timeout_seconds
        path: list[int] = []
        for depth in range(lower, max_depth + 1):
            if self._search(twist, perm, depth, -1, path, deadline, twist_moves, perm_moves, twist_distance, perm_distance, goals):
                moves = [MOVE_NAMES[index] for index in path]
                return TwoByTwoResult(moves, len(moves), "HTM", time.monotonic() - started)
        raise CubeStateError(f"在二阶 HTM {max_depth} 步内未找到解法；请检查识别状态。")

    def _search(
        self, twist: int, perm: int, depth: int, last_face: int, path: list[int], deadline: float | None,
        twist_moves: tuple[array, ...], perm_moves: tuple[array, ...], twist_distance: bytearray,
        perm_distance: bytearray, goals: frozenset[tuple[int, int]],
    ) -> bool:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("二阶最短解搜索超时。")
        if max(twist_distance[twist], perm_distance[perm]) > depth:
            return False
        if depth == 0:
            return (twist, perm) in goals
        for move_index, face in enumerate(MOVE_FACE_INDEX):
            if last_face >= 0 and should_skip_move(last_face, face):
                continue
            child_twist = twist_moves[twist][move_index]
            child_perm = perm_moves[perm][move_index]
            if max(twist_distance[child_twist], perm_distance[child_perm]) > depth - 1:
                continue
            path.append(move_index)
            if self._search(child_twist, child_perm, depth - 1, face, path, deadline, twist_moves, perm_moves, twist_distance, perm_distance, goals):
                return True
            path.pop()
        return False
