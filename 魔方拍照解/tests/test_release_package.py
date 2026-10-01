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
    assert not any(part in {"tests", "docs", "build", "assets", ".cache", ".git", ".venv", "__pycache__"}
                   for name in names for part in name)
    assert not any(name[-1].endswith((".pdb", ".bin", ".pkl", ".exe", ".dll")) for name in names)
    assert ("cube_app", "native.py") not in names
    assert not any(name[-1] in {"requirements-dev.txt", "requirements-release.txt", "setup-dev.ps1"} for name in names)


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
