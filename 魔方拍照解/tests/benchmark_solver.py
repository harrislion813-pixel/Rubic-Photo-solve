from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX
from cube_app.optimal import OptimalSolver, SearchTimeout


CASES = (
    "R D2 B' R L' D' B' L' D' L B R",
    "B2 U' F U' L2 F' D F U B R F' U' F2",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the strict HTM optimal solver.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout for each case in seconds.")
    parser.add_argument("--serial", action="store_true", help="Disable root-branch multiprocessing.")
    parser.add_argument("--workers", type=int, default=None, help="Parallel worker count.")
    args = parser.parse_args()

    solver = OptimalSolver(ROOT / ".cache", parallel=not args.serial, max_workers=args.workers)
    _ = solver.tables
    for sequence in CASES:
        cube = CubieCube()
        for move in sequence.split():
            cube = cube.apply_move_index(MOVE_INDEX[move])
        started = time.perf_counter()
        try:
            result = solver.solve_cube(cube, timeout_seconds=args.timeout)
        except SearchTimeout:
            print(f"timeout  {time.perf_counter() - started:8.3f}s  {sequence}", flush=True)
            continue

        solved = cube
        for move in result.moves:
            solved = solved.apply_move_index(MOVE_INDEX[move])
        if not solved.is_solved():
            raise AssertionError(f"Invalid solution for {sequence}: {result.text}")
        print(
            f"depth={result.depth:2d}  {time.perf_counter() - started:8.3f}s  {sequence}",
            flush=True,
        )


if __name__ == "__main__":
    main()
