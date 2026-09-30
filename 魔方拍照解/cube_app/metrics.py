"""Shared move prices and search budgets for half- and quarter-turn metrics."""

from __future__ import annotations

from collections.abc import Iterable

from .cubie import MOVE_INDEX, MOVE_NAMES


MOVE_COSTS = {
    "HTM": (1,) * len(MOVE_NAMES),
    "QTM": tuple(2 if name.endswith("2") else 1 for name in MOVE_NAMES),
}


def normalize_metric(value: str = "HTM") -> str:
    if isinstance(value, str) and value.upper() in MOVE_COSTS:
        return value.upper()
    raise ValueError("metric 必须为 HTM 或 QTM。")


def move_cost(move: str | int, metric: str = "HTM") -> int:
    prices = MOVE_COSTS[normalize_metric(metric)]
    if isinstance(move, str):
        try:
            return prices[MOVE_INDEX[move]]
        except KeyError:
            pass
    elif isinstance(move, int) and not isinstance(move, bool) and 0 <= move < len(prices):
        return prices[move]
    raise ValueError(f"未知转动：{move!r}")


def solution_cost(moves: Iterable[str | int] | str, metric: str = "HTM") -> int:
    metric = normalize_metric(metric)
    if isinstance(moves, str):
        moves = moves.split()
    return sum(move_cost(move, metric) for move in moves)


def default_max_depth(cube_size: int, metric: str = "HTM") -> int:
    metric = normalize_metric(metric)
    if not isinstance(cube_size, int) or isinstance(cube_size, bool) or cube_size not in (2, 3):
        raise ValueError("cube_size 必须为 2 或 3。")
    return {2: {"HTM": 11, "QTM": 14}, 3: {"HTM": 20, "QTM": 26}}[cube_size][metric]


def resolve_max_depth(cube_size: int, metric: str = "HTM", value: int | None = None) -> int:
    """Validate the generic API budget, then cap it at the selected cube's diameter."""
    metric = normalize_metric(metric)
    diameter = default_max_depth(cube_size, metric)
    if value is None:
        return diameter
    # The public QTM request field historically accepts 40; the physical
    # diameter still caps the work passed to the isolated engine at 26.
    maximum = 40 if metric == "QTM" else default_max_depth(3, metric)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ValueError(f"max_depth 必须为 0–{maximum} 的整数（{metric}）。")
    return min(value, diameter)
