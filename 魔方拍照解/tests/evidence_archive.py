"""Create, verify and restore content-addressed benchmark evidence archives."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_path(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "docs":
        raise ValueError(f"invalid evidence path: {relative}")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"evidence path escapes destination: {relative}")
    return target


def build_archive(root: Path, paths: list[Path], archive: Path, source_commit: str) -> dict:
    files = []
    objects = {}
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        record_path(root, relative)
        data = path.read_bytes()
        sha256 = digest(data)
        files.append({"path": relative, "bytes": len(data), "sha256": sha256})
        objects.setdefault(sha256, data)
    inventory = {"schema": 1, "source_commit": source_commit, "files": files}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for sha256, data in sorted(objects.items()):
            package.writestr(f"objects/{sha256}", data)
        package.writestr("inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2) + "\n")
    return {
        **inventory,
        "archive": {"name": archive.name, "bytes": archive.stat().st_size, "sha256": digest(archive.read_bytes())},
    }


def verified_objects(archive: Path, manifest: dict) -> dict[str, bytes]:
    if (
        archive.stat().st_size != manifest["archive"]["bytes"]
        or digest(archive.read_bytes()) != manifest["archive"]["sha256"]
    ):
        raise ValueError("archive size or SHA-256 mismatch")
    expected = {key: manifest[key] for key in ("schema", "source_commit", "files")}
    objects = {}
    with zipfile.ZipFile(archive) as package:
        if json.loads(package.read("inventory.json")) != expected:
            raise ValueError("internal inventory differs from the versioned manifest")
        names = package.namelist()
        wanted = {f"objects/{item['sha256']}" for item in manifest["files"]} | {"inventory.json"}
        if len(names) != len(set(names)) or set(names) != wanted:
            raise ValueError("unexpected or duplicate archive members")
        for item in manifest["files"]:
            record_path(ROOT, item["path"])
            sha256 = item["sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ValueError("invalid object digest")
            if sha256 not in objects:
                data = package.read(f"objects/{sha256}")
                if digest(data) != sha256:
                    raise ValueError(f"object SHA-256 mismatch: {sha256}")
                objects[sha256] = data
            if len(objects[sha256]) != item["bytes"]:
                raise ValueError(f"object size mismatch: {item['path']}")
    return objects


def restore(archive: Path, manifest: dict, destination: Path, prefix: str) -> dict:
    objects = verified_objects(archive, manifest)
    selected = [item for item in manifest["files"] if item["path"].startswith(prefix)]
    if not selected:
        raise ValueError(f"no archived paths match {prefix!r}")
    restored = skipped = 0
    for item in selected:
        target = record_path(destination, item["path"])
        if target.exists():
            # Current summaries may have been edited since the frozen snapshot.
            # Restoration never overwrites an existing workspace file.
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(objects[item["sha256"]])
        restored += 1
    return {"restored": restored, "existing_files_skipped": skipped, "destination": str(destination.resolve())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify", "restore"))
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/evidence-archive-2026-10-06.json")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--release-url", help="download directory for create")
    parser.add_argument("--destination", type=Path, default=ROOT)
    parser.add_argument("--prefix", default="docs/")
    args = parser.parse_args()
    if args.action == "create":
        if not args.archive or not args.release_url:
            parser.error("create requires --archive and --release-url")
        paths = subprocess.check_output(["git", "ls-files", "-z", "docs"], cwd=ROOT).split(b"\0")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        manifest = build_archive(ROOT, [ROOT / path.decode("utf-8") for path in paths if path], args.archive, commit)
        manifest["archive"]["url"] = args.release_url.rstrip("/") + "/" + args.archive.name
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"files": len(manifest["files"]), "archive": manifest["archive"]}))
        return
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    archive = args.archive or ROOT / "artifacts/evidence" / manifest["archive"]["name"]
    if not archive.exists():
        if args.action != "restore":
            parser.error("verify requires a local archive")
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(manifest["archive"]["url"], archive)
    if args.action == "restore":
        result = restore(archive, manifest, args.destination, args.prefix)
    else:
        objects = verified_objects(archive, manifest)
        result = {
            "verified_files": len(manifest["files"]),
            "unique_objects": len(objects),
            "sha256": manifest["archive"]["sha256"],
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
