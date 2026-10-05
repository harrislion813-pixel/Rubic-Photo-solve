"""Application source selection shared by source packaging and provenance."""

from __future__ import annotations

from pathlib import Path

SHARED_MODULES = ("__init__.py", "cubie.py", "detection.py", "metrics.py", "runtime.py", "vision.py")
WEB = ("index.html", "app.js", "color.js", "solver-client.js", "styles.css")
HISTORICAL_MODULES = (
    "coords.py",
    "fast.py",
    "native.py",
    "optimal.py",
    "tables.py",
    "two_by_two.py",
    "two_by_two_tables.py",
)


def application_sources(root: Path, profile: str | None = None) -> list[Path]:
    required = [root / "cube_app" / name for name in SHARED_MODULES]
    required += [root / name for name in ("server.py", "windows_launcher.py", "pyproject.toml")]
    required += [root / "web" / name for name in WEB]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(f"missing application source: {path}")
    paths = required + list((root / "cube_app" / "solvers").glob("*.py"))
    engines = ("htm",) if profile == "HtmFull" else ("htm", "qtm")
    for engine in engines:
        paths += list((root / "cube_app" / "solvers" / engine).rglob("*.py"))
    paths += list((root / "cube_app" / "service").rglob("*.py"))
    return sorted(set(paths))
