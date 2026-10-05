"""Reject dependency drift before collecting release or regression evidence."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import sys

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def requirements() -> list[Requirement]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    optional = text.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    # These are TOML arrays of strings, also valid Python literals on Python 3.10.
    runtime = ast.literal_eval(re.search(r"dependencies\s*=\s*(\[[\s\S]*?\])", project)[1])
    development = ast.literal_eval(re.search(r"dev\s*=\s*(\[[\s\S]*?\])", optional)[1])
    mirror = [
        line.strip()
        for line in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(("-r", "#"))
    ]
    if sorted(mirror) != sorted(development):
        raise ValueError("requirements-dev.txt differs from pyproject.toml's dev dependencies")
    return [Requirement(value) for value in runtime + development]


def check() -> dict:
    mismatches, versions = [], {}
    for requirement in requirements():
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            actual = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        versions[requirement.name] = actual
        if actual is None or actual not in requirement.specifier:
            mismatches.append(f"{requirement}: installed {actual or 'missing'}")
    for name in ("pip", "setuptools", "wheel", "pluggy", "coverage", "pyinstaller"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "versions": versions,
        "mismatches": mismatches,
        "requirements_sha256": hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = check()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["mismatches"]:
        raise SystemExit("Dependency drift: " + "; ".join(report["mismatches"]) + ". Run setup-dev.ps1.")


if __name__ == "__main__":
    main()
