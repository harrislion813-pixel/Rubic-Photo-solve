"""Assemble clean source and upload-sized, verified release assets."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cube_app import __version__  # noqa: E402

WEB = ("index.html", "app.js", "color.js", "solver-client.js", "styles.css")
USER_SCRIPTS = ("import_runtime.py", "verify_installation.py")


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def source_archive(output):
    name = f"RubicPhotoSolve-{__version__}-source"
    paths = [ROOT / p for p in ("README.md", "CHANGELOG.md", "requirements.txt", "server.py", "windows_launcher.py")]
    paths += sorted((ROOT / "cube_app").rglob("*.py"))
    paths += [ROOT / "web" / p for p in WEB]
    paths += [ROOT / "release" / p for p in USER_SCRIPTS]
    for engine in ("htm", "qtm"):
        native = ROOT / "native" / engine
        paths += sorted((native / "src").glob("*.cpp"))
        paths += sorted((native / "include").glob("*.hpp"))
        paths += [native / "build.ps1", native / "build_tables.ps1"]
    archive = output / (name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in paths:
            package.write(path, arcname=f"{name}/{path.relative_to(ROOT).as_posix()}")
    return archive


def inspect_portable(path):
    with zipfile.ZipFile(path) as package:
        prefix = "RubicPhotoSolve/"
        manifest = json.loads(package.read(prefix + "asset-manifest.json"))
        profile = manifest["profile"]
        if manifest["app_version"] != __version__:
            raise ValueError("portable version mismatch")
        top = {"RubicPhotoSolve.exe", "README-Windows.txt", "README.md", "CHANGELOG.md", "VERSION.txt",
               "asset-manifest.json", "启动魔方求解器.cmd", "校验安装.cmd", "verify_installation.ps1"}
        if profile == "QtmStrong":
            top.add("启动QTM完整强表.cmd")
        allowed = top | set(manifest["files"]) | {"web/" + name for name in WEB}
        for entry in package.infolist():
            relative = entry.filename.removeprefix(prefix)
            if not entry.filename.startswith(prefix) or ".." in Path(relative).parts:
                raise ValueError(f"invalid package path: {entry.filename}")
            if relative.startswith("_internal/"):
                # Bundled third-party licenses and runtime components are retained.
                if any(part in {"tests", "pytest", "ruff", "__pycache__"} for part in Path(relative).parts):
                    raise ValueError(f"development dependency in runtime: {entry.filename}")
            elif relative not in allowed:
                raise ValueError(f"unexpected portable file: {entry.filename}")
        if {entry.filename.removeprefix(prefix) for entry in package.infolist() if not entry.is_dir()} - {
                entry.filename.removeprefix(prefix) for entry in package.infolist()
                if entry.filename.removeprefix(prefix).startswith("_internal/")} != allowed:
            raise ValueError("portable file list is incomplete")
    return manifest


def distribute(portable, output):
    inspect_portable(portable)
    limit = 1536 << 20
    if portable.stat().st_size < 2 << 30:
        target = output / portable.name
        shutil.copy2(portable, target)
        return [target]
    parts = []
    with portable.open("rb") as source:
        number = 1
        while source.tell() < portable.stat().st_size:
            target = output / f"{portable.name}.{number:03d}"
            remaining = limit
            with target.open("wb") as part:
                while remaining:
                    chunk = source.read(min(8 << 20, remaining))
                    if not chunk:
                        break
                    part.write(chunk)
                    remaining -= len(chunk)
            parts.append(target)
            number += 1
    records = [{"name": part.name, "bytes": part.stat().st_size, "sha256": digest(part)} for part in parts]
    identity = digest(portable)
    # Downloaded parts are verified before concatenation; only the task's temporary file is replaced.
    command = "$ErrorActionPreference='Stop'; $root=(Get-Location).Path; "
    command += "function Get-AssetHash([string]$p){$s=[IO.File]::OpenRead($p);$h=[Security.Cryptography.SHA256]::Create();try{([BitConverter]::ToString($h.ComputeHash($s))).Replace('-','').ToLowerInvariant()}finally{$s.Dispose();$h.Dispose()}}; "
    command += "$records=" + "'" + json.dumps(records).replace("'", "''") + "' | ConvertFrom-Json; "
    command += f"$target=Join-Path $root '{portable.name}'; $temp=$target+'.assembling'; "
    command += "foreach($part in $records){$p=Join-Path $root $part.name; "
    command += "if(!(Test-Path -LiteralPath $p -PathType Leaf) -or (Get-Item -LiteralPath $p).Length -ne $part.bytes "
    command += "-or (Get-AssetHash $p) -ne $part.sha256)"
    command += "{throw ('Missing or corrupt download: '+$part.name)}}; "
    command += f"if(Test-Path -LiteralPath $target){{if((Get-AssetHash $target) -eq '{identity}'){{Write-Host 'ZIP already verified.';exit 0}};throw 'Existing ZIP has a different hash. Move it first.'}}; "
    command += "$out=[IO.File]::Create($temp); try{foreach($part in $records){$inputStream=[IO.File]::OpenRead((Join-Path $root $part.name));try{$inputStream.CopyTo($out)}finally{$inputStream.Dispose()}}}finally{$out.Dispose()}; "
    command += f"if((Get-AssetHash $temp) -ne '{identity}'){{throw 'Merged ZIP verification failed.'}}; "
    command += "Move-Item -LiteralPath $temp -Destination $target; Write-Host 'ZIP verified. Extract it and start the app.'"
    encoded = base64.b64encode(command.encode("utf-16le")).decode()
    helper = output / "QTM.cmd"
    helper.write_text('@echo off\r\ncd /d "%~dp0"\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand '
                      + encoded + '\r\nif errorlevel 1 echo Merge failed. Keep this window and read the error.\r\npause\r\n', encoding="ascii")
    return parts + [helper]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--htm", type=Path, required=True)
    parser.add_argument("--qtm", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("use an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    products = [source_archive(output)]
    products += distribute(args.htm.resolve(), output)
    products += distribute(args.qtm.resolve(), output)
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in sorted(products)), encoding="utf-8")
    print(json.dumps({"version": __version__, "files": [{"name": p.name, "bytes": p.stat().st_size} for p in products]}))


if __name__ == "__main__":
    main()
