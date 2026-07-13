from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app import __version__  # noqa: E402


SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def validate_version(tag: str | None = None) -> str:
    if not SEMVER.fullmatch(__version__):
        raise ValueError(f"Canonical version is not SemVer: {__version__}")

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_section = pyproject.split("[project]", 1)[1].split("\n[", 1)[0]
    if not re.search(r'^dynamic\s*=\s*\["version"\]\s*$', project_section, re.MULTILINE):
        raise ValueError("pyproject.toml must read its version from cube_app.__version__")
    if not re.search(
        r'^version\s*=\s*\{\s*attr\s*=\s*"cube_app\.__version__"\s*}\s*$', pyproject, re.MULTILINE
    ):
        raise ValueError("tool.setuptools.dynamic.version must reference cube_app.__version__")
    if re.search(r"^version\s*=", project_section, re.MULTILINE):
        raise ValueError("pyproject.toml must not contain a second static project.version")

    index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    if index_html.count("__APP_VERSION__") < 4:
        raise ValueError("web/index.html must use the server-injected __APP_VERSION__ token")
    if 'meta[name="app-version"]' not in app_js:
        raise ValueError("web/app.js must read the injected app-version meta value")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{__version__}]" not in changelog:
        raise ValueError(f"CHANGELOG.md has no section for {__version__}")

    if tag is not None and tag != f"v{__version__}":
        raise ValueError(f"Release tag {tag!r} does not match canonical version v{__version__}")
    return __version__


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the canonical application version and optional release tag.")
    parser.add_argument("--tag", help="Expected release tag in vX.Y.Z format")
    args = parser.parse_args()
    try:
        print(validate_version(args.tag))
    except (IndexError, KeyError, OSError, ValueError) as exc:
        parser.exit(1, f"version check failed: {exc}\n")


if __name__ == "__main__":
    main()
