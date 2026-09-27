from __future__ import annotations

import pytest

from cube_app.cubie import MOVE_NAMES
from cube_app.metrics import (
    default_max_depth, move_cost, normalize_metric, resolve_max_depth, solution_cost,
)
from cube_app.optimal import invert_moves


@pytest.mark.parametrize("metric", ["HTM", "QTM"])
def test_all_move_prices_and_inverse_cost(metric):
    for index, name in enumerate(MOVE_NAMES):
        expected = 2 if metric == "QTM" and name.endswith("2") else 1
        assert move_cost(name, metric) == expected
        assert move_cost(index, metric) == expected
    assert solution_cost([], metric) == 0
    assert solution_cost("", metric) == 0
    assert solution_cost("R2 U' F2", metric) == (3 if metric == "HTM" else 5)
    assert solution_cost(MOVE_NAMES, metric) == solution_cost(invert_moves(list(MOVE_NAMES)), metric)
    assert move_cost("R'", metric) == 1


@pytest.mark.parametrize("value", [None, "", "STM", " HTM ", 1, True])
def test_invalid_metrics(value):
    with pytest.raises(ValueError, match="metric"):
        normalize_metric(value)


def test_default_and_case_normalization():
    assert normalize_metric() == "HTM"
    assert normalize_metric("htm") == "HTM"
    assert normalize_metric("qTm") == "QTM"


@pytest.mark.parametrize("move", ["R3", "r", "X", "R2'", "", -1, 18, True, 1.5, None])
def test_invalid_moves(move):
    with pytest.raises(ValueError, match="未知转动"):
        move_cost(move, "QTM")


@pytest.mark.parametrize("cube_size,metric,expected", [(2, "HTM", 11), (2, "QTM", 14), (3, "HTM", 20), (3, "QTM", 26)])
def test_default_budget_and_generic_compatibility(cube_size, metric, expected):
    assert default_max_depth(cube_size, metric) == expected
    assert resolve_max_depth(cube_size, metric) == expected
    assert resolve_max_depth(cube_size, metric, default_max_depth(3, metric)) == expected
    assert resolve_max_depth(cube_size, metric, 0) == 0
    assert resolve_max_depth(cube_size, metric, 2) == 2


@pytest.mark.parametrize("metric,values", [("HTM", [-1, 21, 1.0, "1", True]), ("QTM", [-1, 27, 1.0, "1", True])])
def test_invalid_budgets(metric, values):
    for value in values:
        with pytest.raises(ValueError, match="max_depth"):
            resolve_max_depth(3, metric, value)


@pytest.mark.parametrize("cube_size", [1, 4, True, 2.0, "2"])
def test_invalid_cube_sizes(cube_size):
    with pytest.raises(ValueError, match="cube_size"):
        default_max_depth(cube_size)
