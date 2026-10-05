from __future__ import annotations

from pathlib import Path

import pytest

from evidence_archive import build_archive, record_path, restore, verified_objects


def test_archive_deduplicates_verifies_and_restores_without_overwriting(tmp_path):
    source = tmp_path / "source"
    paths = [source / "docs/a.json", source / "docs/b.json"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"same":true}')
    archive = tmp_path / "evidence.zip"
    manifest = build_archive(source, paths, archive, "frozen-commit")
    assert len(verified_objects(archive, manifest)) == 1
    destination = tmp_path / "restored"
    assert restore(archive, manifest, destination, "docs/")["restored"] == 2
    (destination / "docs/a.json").write_bytes(b"current summary")
    assert restore(archive, manifest, destination, "docs/")["existing_files_skipped"] == 2
    assert (destination / "docs/a.json").read_bytes() == b"current summary"
    archive.write_bytes(archive.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verified_objects(archive, manifest)


@pytest.mark.parametrize("relative", ["../escape", "/docs/absolute", "docs/../../escape", "tests/wrong-root"])
def test_restore_rejects_paths_outside_docs(tmp_path: Path, relative):
    with pytest.raises(ValueError, match="invalid evidence path"):
        record_path(tmp_path, relative)
