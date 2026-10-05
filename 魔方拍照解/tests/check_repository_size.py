"""Bound versioned evidence growth; report checkout and Git storage separately."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "tests/repository-size-policy.json"


def evaluate(root: Path, paths: list[Path], policy: dict) -> dict:
    docs_bytes = 0
    violations = []
    exceptions_used = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if relative.startswith("docs/"):
            docs_bytes += size
        if size <= policy["max_file_bytes"]:
            continue
        exception = policy.get("exceptions", {}).get(relative)
        if (
            exception
            and size == exception["bytes"]
            and hashlib.sha256(path.read_bytes()).hexdigest() == exception["sha256"]
        ):
            exceptions_used.append(relative)
        else:
            violations.append(f"{relative}: {size} bytes exceeds single-file budget")
    budget = policy.get("max_docs_bytes")
    if budget is not None and docs_bytes > budget:
        violations.append(f"docs: {docs_bytes} bytes exceeds {budget} byte budget")
    return {
        "versioned_files": len(paths),
        "docs_bytes": docs_bytes,
        "docs_mib": round(docs_bytes / 2**20, 2),
        "exceptions_used": exceptions_used,
        "violations": violations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    listed = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT)
    paths = sorted({ROOT / item.decode("utf-8") for item in listed.split(b"\0") if item})
    report = evaluate(ROOT, [path for path in paths if path.is_file()], json.loads(POLICY.read_text(encoding="utf-8")))
    objects = subprocess.run(["git", "count-objects", "-v"], cwd=ROOT, capture_output=True, text=True, check=True)
    report["git_object_storage"] = {
        key: int(value) for line in objects.stdout.splitlines() for key, value in [line.split(": ", 1)]
    }
    report["storage_note"] = (
        "docs_bytes measures versioned working files; Git storage includes reachable historical evidence and is not promised to shrink by ordinary deletion."
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["violations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
