from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from cube_app.runtime import application_root
from cube_app.solvers.htm.two_by_two import TwoByTwoSolver


class RuntimePathTests(unittest.TestCase):
    def test_source_root_contains_cube_app(self) -> None:
        self.assertTrue((application_root() / "cube_app").is_dir())

    def test_frozen_root_is_executable_directory(self) -> None:
        executable = (Path.cwd() / "portable" / "RubicPhotoSolve.exe").resolve()
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", str(executable)),
        ):
            self.assertEqual(application_root(), executable.parent)
            self.assertEqual(TwoByTwoSolver().cache_dir, executable.parent / ".cache")
