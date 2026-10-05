from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "release"))
from package_release import source_archive  # noqa: E402
from verify_installation import HTM, verify  # noqa: E402
from source_layout import HISTORICAL_MODULES, application_sources  # noqa: E402
from cube_app import __version__  # noqa: E402


def installation(root, version=__version__):
    records = {}
    for relative in HTM:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test runtime asset")
        records[relative] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"app_version": version, "profile": "HtmFull", "files": records}
    (root / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_source_download_contains_runtime_and_build_inputs_without_development_files(tmp_path):
    path = source_archive(tmp_path)
    with zipfile.ZipFile(path) as package:
        names = [Path(name).parts[1:] for name in package.namelist()]
    assert ("server.py",) in names
    assert ("release", "prepare_runtime_caches.py") in names
    assert ("release", "verify_assets.py") in names
    assert ("release", "verify_installation.py") in names
    assert ("pyproject.toml",) in names
    assert ("native", "qtm", "src", "main.cpp") in names
    assert ("native", "htm", "src", "fast.cpp") in names
    assert ("native", "htm", "include", "fast.hpp") in names
    assert ("cube_app", "solvers", "htm", "native_fast.py") in names
    assert not any(part in {"tests", "docs", "build", "assets", ".cache", ".git", ".venv", "__pycache__"}
                   for name in names for part in name)
    assert not any(name[-1].endswith((".pdb", ".bin", ".pkl", ".exe", ".dll")) for name in names)
    assert not any(("cube_app", name) in names for name in HISTORICAL_MODULES)
    assert not any(name[:2] in {("native", "src"), ("native", "include")} for name in names)
    assert ("release", "source_layout.py") in names
    assert ("cube_app", "service", "http_api.py") in names
    assert ("cube_app", "service", "jobs.py") in names
    assert ("cube_app", "service", "solving.py") in names
    assert not any(name[-1] in {"requirements-dev.txt", "requirements-release.txt", "setup-dev.ps1"} for name in names)


def test_provenance_uses_application_allowlist_and_selected_engine(tmp_path):
    import shutil
    shutil.copytree(ROOT / "cube_app", tmp_path / "cube_app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "web", tmp_path / "web")
    for name in ("server.py", "windows_launcher.py", "pyproject.toml"):
        shutil.copy2(ROOT / name, tmp_path / name)
    for name in (*HISTORICAL_MODULES, "unpublished.py"):
        (tmp_path / "cube_app" / name).write_text("# not a delivered application module\n", encoding="utf-8")
    sources = {p.relative_to(tmp_path).as_posix() for p in application_sources(tmp_path, "HtmFull")}
    assert "cube_app/cubie.py" in sources
    assert "cube_app/solvers/htm/native_fast.py" in sources
    assert not any("/qtm/" in path for path in sources)
    assert not any(f"cube_app/{name}" in sources for name in (*HISTORICAL_MODULES, "unpublished.py"))
    assert any("/qtm/" in p.as_posix() for p in application_sources(tmp_path, "QtmStrong"))


def test_asset_verification_rejects_missing_and_corrupted_files(tmp_path):
    manifest = installation(tmp_path)
    assert verify(tmp_path)["profile"] == "HtmFull"
    target = tmp_path / next(iter(manifest["files"]))
    target.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="verification failed"):
        verify(tmp_path)
    target.unlink()
    with pytest.raises(ValueError, match="verification failed"):
        verify(tmp_path)


def test_asset_manifest_rejects_extra_paths(tmp_path):
    manifest = installation(tmp_path)
    manifest["files"]["../escape.exe"] = next(iter(manifest["files"].values()))
    (tmp_path / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly"):
        verify(tmp_path)


def test_import_rejects_other_version_before_writing_source_runtime(tmp_path):
    installation(tmp_path, version="0.0.0")
    result = subprocess.run([sys.executable, str(ROOT / "release/import_runtime.py"), str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "version mismatch" in result.stderr
