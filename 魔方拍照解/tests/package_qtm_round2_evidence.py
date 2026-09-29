"""Archive the round-two sample-level JSON evidence with source hashes."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".cache/qtm-round2"
DESTINATION = ROOT / "docs/benchmarks/qtm-round2-raw-2026-09-29.zip"
INDEX = ROOT / "docs/benchmarks/qtm-round2-raw-index-2026-09-29.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    required = [SOURCE / "final-public48x3x60.json", SOURCE / "final-unseen32x3x60.json",
                ROOT / ".cache/qtm-acceptance-strong-public48x3x60.json"]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    files = sorted(SOURCE.glob("*.json")) + [required[-1],
             ROOT / ".cache/qtm-round2-analysis/coordinate-probe.json"]
    records = []
    with zipfile.ZipFile(DESTINATION, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for path in files:
            if not path.is_file():
                raise FileNotFoundError(path)
            logical = path.relative_to(ROOT).as_posix()
            archive.write(path, logical)
            records.append({"path": logical, "bytes": path.stat().st_size,
                            "sha256": digest(path)})
    index = {"schema_version": 1, "archive": DESTINATION.relative_to(ROOT).as_posix(),
             "archive_bytes": DESTINATION.stat().st_size,
             "archive_sha256": digest(DESTINATION), "raw_files": records}
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"raw_files": len(records), "archive_bytes": index["archive_bytes"],
                      "archive_sha256": index["archive_sha256"]}))


if __name__ == "__main__":
    main()
