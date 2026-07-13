from __future__ import annotations

import json
import subprocess
import sys
import threading
import unittest
import urllib.request
from importlib.metadata import version as package_version
from pathlib import Path

from cube_app import __version__
from server import APP_VERSION, AppHandler, ExclusiveThreadingHTTPServer, HOST


ROOT = Path(__file__).resolve().parents[1]


class VersionTests(unittest.TestCase):
    def test_python_metadata_uses_the_canonical_version(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(APP_VERSION, __version__)
        self.assertEqual(package_version("rubic-photo-solve"), __version__)
        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('version = {attr = "cube_app.__version__"}', pyproject)
        self.assertNotIn('version = "0.1.0"', pyproject)

    def test_release_tag_must_match_canonical_version(self) -> None:
        valid = subprocess.run(
            [sys.executable, "release/check_version.py", "--tag", f"v{__version__}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(valid.stdout.strip(), __version__)

        invalid = subprocess.run(
            [sys.executable, "release/check_version.py", "--tag", "v99.0.0"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("does not match", invalid.stderr)

    def test_server_injects_version_into_frontend(self) -> None:
        server = ExclusiveThreadingHTTPServer((HOST, 0), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://{HOST}:{server.server_address[1]}"
            with urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
                html = response.read().decode("utf-8")
                self.assertEqual(response.headers["X-Cube-App-Version"], __version__)
            self.assertIn(f'content="{__version__}"', html)
            self.assertIn(f"应用版本 v{__version__}", html)
            self.assertNotIn("__APP_VERSION__", html)

            with urllib.request.urlopen(f"{base_url}/api/version", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload, {"ok": True, "version": __version__})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
