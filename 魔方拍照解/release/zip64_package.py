"""Create an atomic ZIP64 archive for the portable Windows directory."""

from __future__ import annotations

import argparse
import json
import os
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    archive = args.archive.resolve()
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + ".writing")
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as package:
            for path in files:
                package.write(path, arcname=Path(directory.name) / path.relative_to(directory))
        os.replace(temporary, archive)
    finally:
        if temporary.exists():
            temporary.unlink()
    with zipfile.ZipFile(archive) as package:
        if len(package.infolist()) != len(files) or any(entry.file_size < 0 for entry in package.infolist()):
            raise RuntimeError("ZIP64 archive index is incomplete")
    print(json.dumps({"ok": True, "archive": str(archive), "files": len(files),
                      "bytes": archive.stat().st_size}))


if __name__ == "__main__":
    main()
