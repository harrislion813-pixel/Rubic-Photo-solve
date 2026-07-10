from __future__ import annotations

from itertools import combinations

from .cubie import CubieCube


N_TWIST = 2187
N_FLIP = 2048
N_SLICE_COMB = 495
N_CORNER_PERM = 40320
N_EDGE8_PERM = 40320
N_SLICE_PERM = 24

SLICE_EDGES = {8, 9, 10, 11}
COMBOS_12_4 = tuple(combinations(range(12), 4))
COMBO_TO_RANK = {combo: rank for rank, combo in enumerate(COMBOS_12_4)}


def get_twist(cube: CubieCube) -> int:
    value = 0
    for idx in range(7):
        value = value * 3 + cube.co[idx]
    return value


def set_twist(coord: int) -> CubieCube:
    co = [0] * 8
    total = 0
    for idx in range(6, -1, -1):
        co[idx] = coord % 3
        total += co[idx]
        coord //= 3
    co[7] = (-total) % 3
    return CubieCube(co=tuple(co))


def get_flip(cube: CubieCube) -> int:
    value = 0
    for idx in range(11):
        value = value * 2 + cube.eo[idx]
    return value


def set_flip(coord: int) -> CubieCube:
    eo = [0] * 12
    total = 0
    for idx in range(10, -1, -1):
        eo[idx] = coord % 2
        total += eo[idx]
        coord //= 2
    eo[11] = total % 2
    return CubieCube(eo=tuple(eo))


def get_slice_comb(cube: CubieCube) -> int:
    positions = tuple(idx for idx, edge in enumerate(cube.ep) if edge in SLICE_EDGES)
    return COMBO_TO_RANK[positions]


def set_slice_comb(coord: int) -> CubieCube:
    selected = set(COMBOS_12_4[coord])
    ep = [-1] * 12
    slice_edge = 8
    normal_edge = 0
    for pos in range(12):
        if pos in selected:
            ep[pos] = slice_edge
            slice_edge += 1
        else:
            ep[pos] = normal_edge
            normal_edge += 1
    return CubieCube(ep=tuple(ep))


def get_corner_perm(cube: CubieCube) -> int:
    return perm_to_rank(cube.cp)


def set_corner_perm(coord: int) -> CubieCube:
    return CubieCube(cp=tuple(rank_to_perm(coord, 8)))


def get_edge8_perm(cube: CubieCube) -> int:
    return perm_to_rank(cube.ep[:8])


def set_edge8_perm(coord: int) -> CubieCube:
    ep8 = rank_to_perm(coord, 8)
    ep = tuple(ep8 + [8, 9, 10, 11])
    return CubieCube(ep=ep)


def get_slice_perm(cube: CubieCube) -> int:
    return perm_to_rank(tuple(edge - 8 for edge in cube.ep[8:12]))


def set_slice_perm(coord: int) -> CubieCube:
    perm = rank_to_perm(coord, 4)
    ep = tuple(list(range(8)) + [edge + 8 for edge in perm])
    return CubieCube(ep=ep)


def perm_to_rank(perm: tuple[int, ...] | list[int]) -> int:
    items = list(range(len(perm)))
    rank = 0
    for value in perm:
        idx = items.index(value)
        rank = rank * len(items) + idx
        del items[idx]
    return rank


def rank_to_perm(rank: int, n: int) -> list[int]:
    digits = [0] * n
    for idx in range(n - 1, -1, -1):
        base = n - idx
        digits[idx] = rank % base
        rank //= base
    items = list(range(n))
    return [items.pop(digit) for digit in digits]

