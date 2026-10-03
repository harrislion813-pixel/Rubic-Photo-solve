"""Verify the final package against source, build and frozen baseline identities."""
from __future__ import annotations

import argparse
import ast
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from freeze_next_speed import ROOT, identity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-version", default="1.10.0")
    args = parser.parse_args()
    package = args.package.resolve()
    manifest = json.loads((package / "asset-manifest.json").read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    assert manifest["profile"] == "QtmStrong" and manifest["app_version"] == args.expected_version
    application_sources = {}
    for relative, digest in manifest["application_source_sha256"].items():
        application_sources[relative] = identity(ROOT / relative)
        assert application_sources[relative]["sha256"] == digest.lower(), relative
    native_builds = {}
    for engine, build in manifest["native_builds"].items():
        assert build["portable"] and not build["profile_guided"]
        relative = f"native/{engine}/build/cube_solver_{engine}.exe"
        binary = identity(package / relative)
        assert binary == current["files"][relative] == identity(ROOT / relative)
        assert binary["sha256"] == build["binary_sha256"].lower()
        sources = {}
        for directory in ("src", "include"):
            for source in (ROOT / f"native/{engine}/{directory}").rglob("*"):
                if source.is_file():
                    sources[source.relative_to(ROOT).as_posix()] = identity(source)
                    assert sources[source.relative_to(ROOT).as_posix()]["sha256"] == build["source_sha256"][source.name].lower()
        native_builds[engine] = {"binary": binary, "build": build, "source_files_verified": len(sources)}
    package_files = {}
    for relative, expected in manifest["files"].items():
        package_files[relative] = identity(package / relative)
        assert package_files[relative] == {k: expected[k] for k in ("bytes", "sha256")}, relative
    asset_paths = [name for name in baseline["files"] if name.startswith(("assets/", ".cache/"))]
    for name in asset_paths:
        assert baseline["files"][name] == current["files"][name] == package_files[name], name
    frozen_files = 0
    for name, expected in baseline["files"].items():
        if not name.startswith(("assets/", ".cache/")):
            assert identity(Path(baseline["snapshot"]) / name) == expected, name
            frozen_files += 1
    wanted = {"server", "cube_app.solvers.htm.fast", "cube_app.solvers.htm.native",
              "cube_app.solvers.qtm.backend", "cube_app.solvers.qtm.native"}
    origins = {}

    def walk(value):
        if isinstance(value, (tuple, list)):
            if len(value) == 3 and isinstance(value[0], str) and value[0] in wanted:
                origins[value[0]] = value[1]
            for item in value:
                walk(item)

    toc = ROOT / ".release-build/QtmStrong/work/RubicPhotoSolve/Analysis-00.toc"
    walk(ast.literal_eval(toc.read_text(encoding="utf-8")))
    assert set(origins) == wanted
    for module, source in origins.items():
        assert Path(source).resolve() == ROOT / (module.replace(".", "/") + ".py")
    archives = list(package.parent.glob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        archive_files = [item for item in archive.infolist() if not item.is_dir()]
        assert len(archive_files) == 153
    support_paths = {path for pattern in ("*next_speed*", "*qtm*next*", "*htm*delivery*", "*pgo*")
                     for path in (ROOT / "tests").glob(pattern) if path.is_file()}
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "package_root": str(package),
              "version": manifest["app_version"], "profile": manifest["profile"],
              "launcher": identity(package / "RubicPhotoSolve.exe"),
              "manifest": identity(package / "asset-manifest.json"),
              "archive": {"path": str(archives[0]), **identity(archives[0]), "files": len(archive_files),
                          "check_scope": "inventory and SHA; full archive verification is recorded separately"},
              "frozen_current_identity": {"path": str(args.current.resolve()), **identity(args.current)},
              "original_baseline_identity": {"path": str(args.baseline.resolve()), **identity(args.baseline)},
              "original_frozen_files_reverified": frozen_files, "unchanged_asset_and_cache_files": len(asset_paths),
              "application_sources": application_sources, "python_module_origins": origins,
              "native_builds": native_builds, "package_files": package_files,
              "support_sources": {path.relative_to(ROOT).as_posix(): identity(path) for path in sorted(support_paths)},
              "default_flags": {"CUBE_HTM_EARLY_CANDIDATE": "off", "CUBE_QTM_EXPANSION": "generic",
                                "CUBE_QTM_CANDIDATE_SCHEDULE": "legacy", "CUBE_QTM_LATE_TAIL_IMPROVEMENT": "off"},
              "scope": "conservative defaults with resource repair; experimental 72-run speed results do not apply to this package",
              "failures": []}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("version", "profile", "original_frozen_files_reverified",
                                           "unchanged_asset_and_cache_files", "archive", "failures")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
