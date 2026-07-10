from __future__ import annotations

import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from cube_app.tables import CACHE_VERSION, SolverTables, load_or_build_tables


def empty_tables() -> SolverTables:
    return SolverTables(
        twist_move=(array("H"),),
        flip_move=(array("H"),),
        slice_comb_move=(array("H"),),
        corner_perm_all_move=(array("H"),),
        corner_perm_move=(array("H"),),
        edge8_perm_move=(array("H"),),
        slice_perm_move=(array("H"),),
        twist_flip_prune=bytearray(),
        corner_perm_prune=bytearray(),
        twist_slice_prune=bytearray(),
        flip_slice_prune=bytearray(),
        corner_slice_prune=bytearray(),
        edge8_slice_prune=bytearray(),
        slice_solved=0,
    )


class TableCacheTests(unittest.TestCase):
    def test_corrupted_cache_is_rebuilt_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / f"solver_tables_v{CACHE_VERSION}.pkl"
            cache_path.write_bytes(b"not a pickle")
            expected = empty_tables()

            with patch("cube_app.tables.build_tables", return_value=expected) as builder:
                actual = load_or_build_tables(directory)

            self.assertIs(actual, expected)
            builder.assert_called_once_with()
            self.assertEqual(load_or_build_tables(directory), expected)
            self.assertFalse(list(Path(directory).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
