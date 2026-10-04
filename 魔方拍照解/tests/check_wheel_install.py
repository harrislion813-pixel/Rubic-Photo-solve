"""Install the wheel in a clean venv and import the isolated solver adapters."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv
import zipfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel_directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    wheels = list(args.wheel_directory.glob("rubic_photo_solve-*.whl"))
    if len(wheels) != 1:
        parser.error("expected exactly one application wheel")
    wheel = wheels[0].resolve()
    with zipfile.ZipFile(wheel) as archive:
        entries = [name for name in archive.namelist() if name.startswith("cube_app/solvers/")]
    if not entries:
        raise AssertionError("wheel omitted the isolated solver packages")
    with tempfile.TemporaryDirectory(prefix="cube-wheel-") as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-X", "utf8", "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
                       check=True, capture_output=True, text=True, encoding="utf-8")
        code = (
            "import json,pathlib,cube_app; "
            "import cube_app.solvers.htm.native,cube_app.solvers.htm.native_fast,cube_app.solvers.qtm.native; "
            "import cube_app.solvers.qtm.backend,cube_app.solvers.resource_broker; "
            "print(json.dumps({'version':cube_app.__version__,'module':cube_app.__file__}))"
        )
        completed = subprocess.run([str(python), "-I", "-X", "utf8", "-c", code], cwd=root, check=True,
                                   capture_output=True, text=True, encoding="utf-8")
        installed = json.loads(completed.stdout)
        if not Path(installed["module"]).resolve().is_relative_to(root):
            raise AssertionError("imports escaped the isolated installation")
    result = {"wheel": str(wheel), "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "solver_entries": len(entries), "isolated_imports": "passed", "installed": installed}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
