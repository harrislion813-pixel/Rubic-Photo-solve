from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


FACE_NAMES = ("U", "R", "F", "D", "L", "B")
FACE_TO_INDEX = {face: idx for idx, face in enumerate(FACE_NAMES)}

MOVE_FACES = ("U", "R", "F", "D", "L", "B")
MOVE_SUFFIXES = ("", "2", "'")
MOVE_NAMES = tuple(face + suffix for face in MOVE_FACES for suffix in MOVE_SUFFIXES)
MOVE_FACE_INDEX = tuple(FACE_TO_INDEX[name[0]] for name in MOVE_NAMES)
MOVE_INDEX = {name: idx for idx, name in enumerate(MOVE_NAMES)}

PHASE2_MOVE_NAMES = ("U", "U2", "U'", "R2", "F2", "D", "D2", "D'", "L2", "B2")
PHASE2_MOVES = tuple(MOVE_INDEX[name] for name in PHASE2_MOVE_NAMES)

OPPOSITE_FACE = {
    FACE_TO_INDEX["U"]: FACE_TO_INDEX["D"],
    FACE_TO_INDEX["D"]: FACE_TO_INDEX["U"],
    FACE_TO_INDEX["R"]: FACE_TO_INDEX["L"],
    FACE_TO_INDEX["L"]: FACE_TO_INDEX["R"],
    FACE_TO_INDEX["F"]: FACE_TO_INDEX["B"],
    FACE_TO_INDEX["B"]: FACE_TO_INDEX["F"],
}


CORNER_FACELETS = (
    (8, 9, 20),     # URF: U9 R1 F3
    (6, 18, 38),    # UFL: U7 F1 L3
    (0, 36, 47),    # ULB: U1 L1 B3
    (2, 45, 11),    # UBR: U3 B1 R3
    (29, 26, 15),   # DFR: D3 F9 R7
    (27, 44, 24),   # DLF: D1 L9 F7
    (33, 53, 42),   # DBL: D7 B9 L7
    (35, 17, 51),   # DRB: D9 R9 B7
)

CORNER_COLORS = (
    ("U", "R", "F"),
    ("U", "F", "L"),
    ("U", "L", "B"),
    ("U", "B", "R"),
    ("D", "F", "R"),
    ("D", "L", "F"),
    ("D", "B", "L"),
    ("D", "R", "B"),
)

EDGE_FACELETS = (
    (5, 10),   # UR: U6 R2
    (7, 19),   # UF: U8 F2
    (3, 37),   # UL: U4 L2
    (1, 46),   # UB: U2 B2
    (32, 16),  # DR: D6 R8
    (28, 25),  # DF: D2 F8
    (30, 43),  # DL: D4 L8
    (34, 52),  # DB: D8 B8
    (23, 12),  # FR: F6 R4
    (21, 41),  # FL: F4 L6
    (50, 39),  # BL: B6 L4
    (48, 14),  # BR: B4 R6
)

EDGE_COLORS = (
    ("U", "R"),
    ("U", "F"),
    ("U", "L"),
    ("U", "B"),
    ("D", "R"),
    ("D", "F"),
    ("D", "L"),
    ("D", "B"),
    ("F", "R"),
    ("F", "L"),
    ("B", "L"),
    ("B", "R"),
)


class CubeStateError(ValueError):
    """Raised when a facelet string is not a legal cube state."""


@dataclass(frozen=True, slots=True)
class CubieCube:
    cp: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7)
    co: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0, 0)
    ep: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
    eo: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    def moved(self, move: "CubieCube") -> "CubieCube":
        cp = tuple(self.cp[move.cp[i]] for i in range(8))
        co = tuple((self.co[move.cp[i]] + move.co[i]) % 3 for i in range(8))
        ep = tuple(self.ep[move.ep[i]] for i in range(12))
        eo = tuple((self.eo[move.ep[i]] + move.eo[i]) % 2 for i in range(12))
        return CubieCube(cp, co, ep, eo)

    def apply_move_index(self, move_index: int) -> "CubieCube":
        return self.moved(all_move_cubes()[move_index])

    def is_solved(self) -> bool:
        return (
            self.cp == (0, 1, 2, 3, 4, 5, 6, 7)
            and self.co == (0, 0, 0, 0, 0, 0, 0, 0)
            and self.ep == (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
            and self.eo == (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        )


SOLVED_FACELETS = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"


def clean_facelets(facelets: str) -> str:
    compact = "".join(ch for ch in facelets.upper() if ch in FACE_TO_INDEX)
    if len(compact) != 54:
        raise CubeStateError("需要 54 个面贴字符，顺序为 U R F D L B。")
    counts = {face: compact.count(face) for face in FACE_NAMES}
    wrong = {face: count for face, count in counts.items() if count != 9}
    if wrong:
        detail = ", ".join(f"{face}={count}" for face, count in wrong.items())
        raise CubeStateError(f"每种颜色必须正好 9 个，当前数量异常：{detail}")
    for center_index, face in zip((4, 13, 22, 31, 40, 49), FACE_NAMES):
        if compact[center_index] != face:
            raise CubeStateError("中心块必须按 U R F D L B 顺序固定；请检查六面放置和基准方向。")
    return compact


def from_facelets(facelets: str, validate: bool = True) -> CubieCube:
    f = clean_facelets(facelets)
    cp = [-1] * 8
    co = [-1] * 8
    ep = [-1] * 12
    eo = [-1] * 12

    for pos in range(8):
        ori = None
        for candidate_ori in range(3):
            color = f[CORNER_FACELETS[pos][candidate_ori]]
            if color in ("U", "D"):
                ori = candidate_ori
                break
        if ori is None:
            raise CubeStateError(f"角块位置 {pos + 1} 缺少 U/D 色。")

        color1 = f[CORNER_FACELETS[pos][(ori + 1) % 3]]
        color2 = f[CORNER_FACELETS[pos][(ori + 2) % 3]]
        for cubie in range(8):
            if CORNER_COLORS[cubie][1] == color1 and CORNER_COLORS[cubie][2] == color2:
                cp[pos] = cubie
                co[pos] = ori % 3
                break
        if cp[pos] < 0:
            raise CubeStateError(f"无法识别角块位置 {pos + 1} 的颜色组合。")

    for pos in range(12):
        color0 = f[EDGE_FACELETS[pos][0]]
        color1 = f[EDGE_FACELETS[pos][1]]
        for cubie in range(12):
            if EDGE_COLORS[cubie][0] == color0 and EDGE_COLORS[cubie][1] == color1:
                ep[pos] = cubie
                eo[pos] = 0
                break
            if EDGE_COLORS[cubie][0] == color1 and EDGE_COLORS[cubie][1] == color0:
                ep[pos] = cubie
                eo[pos] = 1
                break
        if ep[pos] < 0:
            raise CubeStateError(f"无法识别棱块位置 {pos + 1} 的颜色组合。")

    cube = CubieCube(tuple(cp), tuple(co), tuple(ep), tuple(eo))
    if validate:
        validate_cube(cube)
    return cube


def to_facelets(cube: CubieCube) -> str:
    facelets = list(SOLVED_FACELETS)
    for pos in range(8):
        cubie = cube.cp[pos]
        ori = cube.co[pos]
        for n in range(3):
            facelets[CORNER_FACELETS[pos][(n + ori) % 3]] = CORNER_COLORS[cubie][n]
    for pos in range(12):
        cubie = cube.ep[pos]
        ori = cube.eo[pos]
        for n in range(2):
            facelets[EDGE_FACELETS[pos][(n + ori) % 2]] = EDGE_COLORS[cubie][n]
    return "".join(facelets)


def validate_cube(cube: CubieCube) -> None:
    if sorted(cube.cp) != list(range(8)):
        raise CubeStateError("角块集合不完整或有重复。")
    if sorted(cube.ep) != list(range(12)):
        raise CubeStateError("棱块集合不完整或有重复。")
    if sum(cube.co) % 3 != 0:
        raise CubeStateError("角块朝向不合法，请检查识别或手动校正。")
    if sum(cube.eo) % 2 != 0:
        raise CubeStateError("棱块翻转不合法，请检查识别或手动校正。")
    if permutation_parity(cube.cp) != permutation_parity(cube.ep):
        raise CubeStateError("角块和棱块奇偶性不一致，不是合法三阶魔方状态。")


def permutation_parity(values: Iterable[int]) -> int:
    seq = list(values)
    inversions = 0
    for i, left in enumerate(seq):
        for right in seq[i + 1 :]:
            if left > right:
                inversions ^= 1
    return inversions


def should_skip_move(last_face: int, face: int) -> bool:
    if last_face is None:
        return False
    if last_face == face:
        return True
    return OPPOSITE_FACE[last_face] == face and last_face > face


@lru_cache(maxsize=1)
def all_move_cubes() -> tuple[CubieCube, ...]:
    base = single_turn_cubes()
    moves: list[CubieCube] = []
    solved = CubieCube()
    for cube in base:
        current = solved
        for _ in range(3):
            current = current.moved(cube)
            moves.append(current)
    return tuple(moves)


@lru_cache(maxsize=1)
def single_turn_cubes() -> tuple[CubieCube, ...]:
    permutations = facelet_move_permutations()
    return tuple(from_facelets(apply_facelet_permutation(SOLVED_FACELETS, perm), validate=False) for perm in permutations)


def apply_facelet_permutation(facelets: str, permutation: tuple[int, ...]) -> str:
    result = list(facelets)
    for old_idx, new_idx in enumerate(permutation):
        result[new_idx] = facelets[old_idx]
    return "".join(result)


def facelet_move_permutations() -> tuple[tuple[int, ...], ...]:
    sticker_to_index, index_to_sticker = build_sticker_geometry()
    specs = (
        ("U", 1, (0, 1, 0)),
        ("R", 1, (1, 0, 0)),
        ("F", 1, (0, 0, 1)),
        ("D", -1, (0, -1, 0)),
        ("L", -1, (-1, 0, 0)),
        ("B", -1, (0, 0, -1)),
    )
    axis_for_face = {"U": 1, "D": 1, "R": 0, "L": 0, "F": 2, "B": 2}
    permutations = []
    for face, layer_sign, axis_vector in specs:
        axis = axis_for_face[face]
        perm = list(range(54))
        for idx, (pos, normal) in enumerate(index_to_sticker):
            if pos[axis] != layer_sign:
                continue
            new_pos = rotate_minus_90(pos, axis_vector)
            new_normal = rotate_minus_90(normal, axis_vector)
            perm[idx] = sticker_to_index[(new_pos, new_normal)]
        permutations.append(tuple(perm))
    return tuple(permutations)


def build_sticker_geometry() -> tuple[dict[tuple[tuple[int, int, int], tuple[int, int, int]], int], list[tuple[tuple[int, int, int], tuple[int, int, int]]]]:
    index_to_sticker: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = [((0, 0, 0), (0, 0, 0))] * 54

    def set_sticker(index: int, pos: tuple[int, int, int], normal: tuple[int, int, int]) -> None:
        index_to_sticker[index] = (pos, normal)

    # U face: rows go from back to front, columns from left to right.
    for r in range(3):
        for c in range(3):
            set_sticker(r * 3 + c, (c - 1, 1, r - 1), (0, 1, 0))

    # R face: rows top to bottom, columns front to back.
    for r in range(3):
        for c in range(3):
            set_sticker(9 + r * 3 + c, (1, 1 - r, 1 - c), (1, 0, 0))

    # F face: rows top to bottom, columns left to right.
    for r in range(3):
        for c in range(3):
            set_sticker(18 + r * 3 + c, (c - 1, 1 - r, 1), (0, 0, 1))

    # D face: rows front to back, columns left to right.
    for r in range(3):
        for c in range(3):
            set_sticker(27 + r * 3 + c, (c - 1, -1, 1 - r), (0, -1, 0))

    # L face: rows top to bottom, columns back to front.
    for r in range(3):
        for c in range(3):
            set_sticker(36 + r * 3 + c, (-1, 1 - r, c - 1), (-1, 0, 0))

    # B face: rows top to bottom, columns right to left.
    for r in range(3):
        for c in range(3):
            set_sticker(45 + r * 3 + c, (1 - c, 1 - r, -1), (0, 0, -1))

    sticker_to_index = {sticker: idx for idx, sticker in enumerate(index_to_sticker)}
    if len(sticker_to_index) != 54:
        raise RuntimeError("Internal sticker geometry is not unique.")
    return sticker_to_index, index_to_sticker


def rotate_minus_90(
    vector: tuple[int, int, int],
    axis_vector: tuple[int, int, int],
) -> tuple[int, int, int]:
    x, y, z = vector
    ax, ay, az = axis_vector
    if ax:
        sign = ax
        return (x, sign * z, -sign * y)
    if ay:
        sign = ay
        return (-sign * z, y, sign * x)
    sign = az
    return (sign * y, -sign * x, z)
