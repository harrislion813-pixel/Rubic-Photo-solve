"""Import verified acceleration assets from a portable package of the same version."""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cube_app import __version__  # noqa: E402
from verify_installation import verify  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("portable", type=Path)
    args = parser.parse_args()
    portable = args.portable.resolve()
    if portable == ROOT:
        parser.error("choose the extracted portable package, not the source directory")
    manifest = verify(portable)
    if manifest["app_version"] != __version__:
        parser.error(f"version mismatch: portable {manifest['app_version']}, source {__version__}")
    # Verify every source file before changing the destination.
    for relative in manifest["files"]:
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(portable / relative, destination)
    (ROOT / "asset-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    verify(ROOT)
    print(f"Imported verified {manifest['profile']} assets for {__version__}")


if __name__ == "__main__":
    main()
