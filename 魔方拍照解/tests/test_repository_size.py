from __future__ import annotations

import hashlib

from check_repository_size import evaluate


def test_exception_cannot_hide_changed_or_new_large_evidence(tmp_path):
    path = tmp_path / "docs/old.json"
    path.parent.mkdir()
    path.write_bytes(b"old evidence")
    policy = {
        "max_file_bytes": 5,
        "max_docs_bytes": None,
        "exceptions": {
            "docs/old.json": {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        },
    }
    assert not evaluate(tmp_path, [path], policy)["violations"]
    path.write_bytes(b"new evidence")
    assert evaluate(tmp_path, [path], policy)["violations"]
    new_path = tmp_path / "docs/new.json"
    new_path.write_bytes(b"new evidence")
    assert evaluate(tmp_path, [new_path], policy)["violations"]


def test_total_budget_is_enabled_only_after_archive_migration(tmp_path):
    path = tmp_path / "docs/summary.json"
    path.parent.mkdir()
    path.write_bytes(b"summary")
    policy = {"max_file_bytes": 10, "max_docs_bytes": None, "exceptions": {}}
    assert not evaluate(tmp_path, [path], policy)["violations"]
    policy["max_docs_bytes"] = 5
    assert evaluate(tmp_path, [path], policy)["violations"]
