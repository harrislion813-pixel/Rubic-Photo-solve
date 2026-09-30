"""Build frozen H0 and compare portable complete layers to isolated H1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
H0 = "ae73ca81af1ed077c059f3345377190bf0ce2882"


def main() -> None:
    source = ROOT / ".cache" / "htm-portable-h0-source"
    source.mkdir(parents=True, exist_ok=True)
    audit = {"source": H0, "files": {}, "build_script": "current portable HTM build.ps1"}
    for current in sorted((ROOT / "native/htm").glob("**/*")):
        if current.suffix not in {".cpp", ".hpp"} or current.parent.name not in {"src", "include"}:
            continue
        relative = current.relative_to(ROOT / "native/htm")
        old = subprocess.check_output(["git", "show", f"{H0}:魔方拍照解/native/{relative.as_posix()}"], cwd=ROOT)
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(old)
        current_bytes = current.read_bytes()
        if old.replace(b"\r\n", b"\n") != current_bytes.replace(b"\r\n", b"\n"):
            raise AssertionError(f"HTM source changed: {relative}")
        audit["files"][relative.as_posix()] = {
            "git_sha256": hashlib.sha256(old).hexdigest(),
            "worktree_sha256": hashlib.sha256(current_bytes).hexdigest(),
            "equal_except_line_endings": True,
        }
    shutil.copyfile(ROOT / "native/htm/build.ps1", source / "build.ps1")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise RuntimeError("PowerShell is required for Windows portable builds")
    binary = source / "build/cube_solver_htm.exe"
    info_path = source / "build/build-info.json"
    info = json.loads(info_path.read_text(encoding="utf-8-sig")) if info_path.is_file() else {}
    valid = binary.is_file() and info.get("portable") and info.get("binary_sha256", "").lower() == (
        hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None
    )
    valid = valid and all(info.get("source_sha256", {}).get(Path(name).name, "").lower() == values["git_sha256"]
                          for name, values in audit["files"].items())
    if not valid:
        completed = subprocess.run([shell, "-NoProfile", "-File", str(source / "build.ps1"), "-Portable"],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (ROOT / "docs/benchmarks/htm-portable-h0-build.log").write_text(
            completed.stdout + completed.stderr, encoding="utf-8")
        completed.check_returncode()
    audit["build_info"] = json.loads(info_path.read_text(encoding="utf-8-sig"))
    (ROOT / "docs/benchmarks/htm-portable-source-audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8")
    for label, binary in (("h0", source / "build/cube_solver_htm.exe"),
                          ("h1", ROOT / "native/htm/build/cube_solver_htm.exe")):
        subprocess.run([sys.executable, str(ROOT / "tests/benchmark_isolation_short.py"),
                        "--binary", str(binary), "--metric", "HTM", "--bound", "16", "--bound-pgo", "15",
                        "--label", f"htm-{label}-portable", "--output",
                        str(ROOT / f"docs/benchmarks/htm-{label}-portable-review.json")], check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
