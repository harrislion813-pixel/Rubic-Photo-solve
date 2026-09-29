"""Reproducible HTM/QTM benchmark with proof-cache reuse explicitly disabled."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import random
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cube_app.cubie import CubieCube, MOVE_INDEX, from_facelets, to_facelets
from cube_app.optimal import invert_moves
from cube_app.metrics import default_max_depth, normalize_metric, solution_cost


def legal_state(seed: int) -> CubieCube:
    rng = random.Random(seed)
    cp, ep = list(range(8)), list(range(12))
    rng.shuffle(cp)
    rng.shuffle(ep)

    def parity(values):
        return sum(values[i] > values[j] for i in range(len(values)) for j in range(i + 1, len(values))) % 2

    if parity(cp) != parity(ep):
        ep[0], ep[1] = ep[1], ep[0]
    co = [rng.randrange(3) for _ in range(7)]
    eo = [rng.randrange(2) for _ in range(11)]
    return CubieCube(tuple(cp), tuple(co + [-sum(co) % 3]), tuple(ep), tuple(eo + [sum(eo) % 2]))


def case_state(case: dict) -> tuple[CubieCube, list[str]]:
    if case.get("superflip"):
        return CubieCube(eo=(1,) * 12), []
    if "legal_seed" in case:
        return legal_state(case["legal_seed"]), []
    if "facelets" in case:
        return from_facelets(case["facelets"]), case.get("incumbent", [])
    cube = CubieCube()
    for name in case["scramble"].split():
        cube = cube.apply_move_index(MOVE_INDEX[name])
    return cube, invert_moves(case["scramble"].split())


def file_metadata(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def peak_memory(process: subprocess.Popen) -> int | None:
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if get_memory(int(process._handle), ctypes.byref(counters), counters.cb):
        return int(counters.PeakWorkingSetSize)
    return None


class Service:
    def __init__(self, binary: Path, flags: list[str], pdb_flags: list[str], startup_timeout: float = 30):
        started = time.perf_counter()
        self.process = subprocess.Popen(
            [str(binary.resolve()), "serve", "--no-proof-cache", *pdb_flags, *flags],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.lines = queue.Queue()
        self.errors = []
        self.asset_events = []

        def read_stdout():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)

        def read_stderr():
            for line in self.process.stderr:
                self.errors.append(line.rstrip())

        self.reader = threading.Thread(target=read_stdout, daemon=True)
        self.error_reader = threading.Thread(target=read_stderr, daemon=True)
        self.reader.start()
        self.error_reader.start()
        try:
            ready = self.event(startup_timeout)
            if ready.get("type") != "ready" or not ready.get("ok") or ready.get("protocol_version") != 3:
                raise RuntimeError(ready)
        except Exception:
            self.close()
            raise
        self.startup_seconds = time.perf_counter() - started
        self.ready = ready

    def event(self, timeout: float) -> dict:
        line = self.lines.get(timeout=timeout)
        if line is None:
            raise RuntimeError("native service stopped: " + "\n".join(self.errors[-5:]))
        return json.loads(line)

    def solve(self, case: dict, threads: int, timeout: float, metric: str = "HTM",
              max_cost: int | None = None, incumbent_mode: str = "fixed") -> dict:
        cube, incumbent = case_state(case)
        if incumbent_mode == "none":
            incumbent = []
        budget = default_max_depth(3, metric) if max_cost is None else max_cost
        started = time.perf_counter()
        self.process.stdin.write(
            f"solve\tbenchmark\t{to_facelets(cube)}\t{budget}\t{timeout}\t{threads}\t{metric}\t{' '.join(incumbent)}\n"
        )
        self.process.stdin.flush()
        events = []
        candidates = []
        while True:
            event = self.event(timeout + 10)
            if event.get("type") == "progress":
                events.append(event)
                continue
            if event.get("type") == "candidate":
                candidates.append({"at_seconds": time.perf_counter() - started, **event})
                continue
            if event.get("type") == "asset_ready":
                self.asset_events.append({"at_seconds": time.perf_counter() - started, **event})
                continue
            if not event.get("ok"):
                raise RuntimeError(event)
            break
        if event.get("depth", -1) >= 0:
            verified = cube
            for name in event.get("moves", []):
                verified = verified.apply_move_index(MOVE_INDEX[name])
            if not verified.is_solved() or event.get("metric") != metric or event["depth"] != solution_cost(event.get("moves", []), metric):
                raise AssertionError("invalid native solution")
        expected = case.get("expected_depth" if metric == "HTM" else "expected_qtm_depth")
        if event.get("optimal") and expected is not None and event["depth"] != expected:
            raise AssertionError(f"incorrect optimal depth for {case['name']}")
        return {
            "case": case["name"],
            "facelets": to_facelets(cube),
            "incumbent": incumbent,
            "metric": metric,
            "incumbent_depth": solution_cost(incumbent, metric) if incumbent else None,
            "incumbent_mode": incumbent_mode,
            "max_cost": budget,
            "proof_cache_reuse": False,
            "threads": threads,
            "wall_seconds": time.perf_counter() - started,
            "result": event,
            "events": events,
            "candidates": candidates,
            "completed_depth": event.get("completed_depth", max((p["completed_depth"] for p in events), default=-1)),
            "process_peak_memory_bytes": peak_memory(self.process),
        }

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=2)
        self.error_reader.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


def summary(runs: list[dict]) -> dict:
    wall = sorted(run["wall_seconds"] for run in runs)
    complete = [run for run in runs if run["result"].get("optimal")]
    proof_times = sorted(run["result"]["elapsed_seconds"] for run in complete)
    return {
        "runs": len(runs),
        "completed": len(complete),
        "timeout_ratio": (len(runs) - len(complete)) / len(runs),
        "all_run_wall_p50": statistics.median(wall),
        "all_run_wall_p95": wall[min(len(wall) - 1, int(len(wall) * 0.95))],
        "successful_proof_p50": statistics.median(proof_times) if proof_times else None,
        "completed_depths": [run["completed_depth"] for run in runs],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "native/build/cube_solver.exe")
    parser.add_argument("--cases-file", type=Path, default=Path(__file__).with_name("native_cases.json"))
    parser.add_argument("--cases", default="repo14,pgo16,seed18,known18")
    parser.add_argument("--threads", default="16")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--metric", choices=("HTM", "QTM"), type=normalize_metric, default="HTM")
    parser.add_argument("--profile", default="baseline", help="Named profile in --pdb-manifest")
    parser.add_argument("--pdb-manifest", type=Path)
    parser.add_argument("--max-cost", type=int)
    parser.add_argument("--incumbent-mode", choices=("fixed", "none"), default="fixed")
    parser.add_argument("--native-flag", action="append", default=[], help="One native optimization switch per use")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--variants", default="baseline,pruning,staged")
    parser.add_argument("--no-tail", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/native-benchmark.json")
    args = parser.parse_args()
    choices = {
        "baseline": ["--no-axis-strengthening", "--keep-small-tables", "--no-staged-expansion"],
        "pruning": ["--no-staged-expansion"],
        "staged": [],
    }
    variants = args.variants.split(",")
    allowed_flags = {"--no-qtm-parity", "--no-axis-strengthening", "--keep-small-tables",
                     "--no-native-candidate", "--legacy-split", "--tt-every-node",
                     "--no-staged-expansion", "--no-direction-probe", "--inverse-direction",
                     "--transposition", "--no-transposition",
                     *(f"--coordinate-kernel={value}" for value in ("reference", "affine")),
                     *(f"--qtm-axis-rule={value}" for value in ("off", "phase1", "strong", "both")),
                     *(f"--direction-policy={value}" for value in ("off", "legacy", "bounded")),
                     *(f"--dual-policy={value}" for value in ("off", "root", "selective", "all")),
                     "--bpmx=off", "--bpmx=on"}
    allowed_flags.update(f"--pdb-query-order={value}" for value in ("legacy", "interleaved", "strong-first"))
    allowed_flags.update(("--pdb-prefetch=off", "--pdb-prefetch=on"))
    allowed_flags.update(("--asset-loading=eager", "--asset-loading=staged"))
    if (not set(variants) <= choices.keys() or args.repeats < 1 or args.timeout <= 0 or args.startup_timeout <= 0
            or args.max_cost is not None and not 0 <= args.max_cost <= default_max_depth(3, args.metric)
            or not set(args.native_flag) <= allowed_flags):
        parser.error("invalid variants, repeats or timeout")
    cases = json.loads(args.cases_file.read_text(encoding="utf-8"))
    selected = cases if args.cases == "all" else [c for c in cases if c["name"] in args.cases.split(",")]
    if not selected:
        parser.error("no matching benchmark cases")
    for case in selected:
        state, _ = case_state(case)
        from_facelets(to_facelets(state))
    asset_flags = {"corner": "--pdb", "phase1": "--phase1-pdb", "tail": "--tail-pdb",
                   "qtm_tail": "--qtm-tail-pdb",
                   "qtm_corner": "--qtm-pdb", "qtm_phase1": "--qtm-phase1-pdb",
                   "qtm_edge_a": "--qtm-edge-pdb-a", "qtm_edge_b": "--qtm-edge-pdb-b",
                   "qtm_strong": "--strong-pdb",
                   **{f"edge_{chr(ord('a') + i)}": f"--edge-pdb-{chr(ord('a') + i)}" for i in range(8)}}
    if args.pdb_manifest:
        manifest = json.loads(args.pdb_manifest.read_text(encoding="utf-8-sig"))
        profile = manifest.get("profiles", {}).get(args.profile)
        if not isinstance(profile, dict) or not isinstance(profile.get("assets"), dict):
            parser.error("selected profile is missing from PDB manifest")
        assets = profile["assets"]
    elif args.profile == "baseline":
        assets = {"corner": ".cache/native/corner_htm_v2.pdb",
                  "phase1": ".cache/native/phase1_sym_htm_v2.pdb"}
        tail = ROOT / ".cache/native/tail_depth6_v4.pdb"
        if tail.is_file():
            assets["tail"] = str(tail)
    else:
        parser.error("the selected profile requires --pdb-manifest")
    if set(assets) - asset_flags.keys():
        parser.error("PDB manifest has unsupported asset names")
    pdb_paths = []
    pdb_flags = []
    for name, value in assets.items():
        if name in {"tail", "qtm_tail"} and args.no_tail:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            parser.error(f"missing {name} asset: {path}")
        pdb_paths.append(path)
        pdb_flags += [asset_flags[name], str(path)]
    output = {
        "metric": args.metric,
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "repeats": args.repeats,
        "variants": variants,
        "profile": args.profile,
        "pdb_manifest": file_metadata(args.pdb_manifest) if args.pdb_manifest else None,
        "max_cost": args.max_cost,
        "incumbent_mode": args.incumbent_mode,
        "native_flags": args.native_flag,
        "proof_cache_reuse": False,
        "tail_enabled": None,
        "binary": file_metadata(args.binary),
        "pdbs": [file_metadata(p) for p in pdb_paths],
        "cases_file": file_metadata(args.cases_file),
        "selected_cases": [
            {"name": case["name"], "facelets": to_facelets(case_state(case)[0]), "incumbent": case_state(case)[1]}
            for case in selected
        ],
        "cold_starts": [],
        "runs": [],
        "summaries": {},
    }
    metadata = args.binary.with_name("build-info.json")
    if metadata.is_file():
        output["build"] = json.loads(metadata.read_text(encoding="utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for repeat in range(args.repeats):
        # Alternate ordering to reduce version-grouped thermal/frequency bias.
        for variant in variants if repeat % 2 == 0 else list(reversed(variants)):
            service = Service(args.binary, [*choices[variant], *args.native_flag], pdb_flags, args.startup_timeout)
            output["cold_starts"].append(
                {"variant": variant, "repeat": repeat, "seconds": service.startup_seconds, "ready": service.ready}
            )
            try:
                for threads in map(int, args.threads.split(",")):
                    for case in selected:
                        run = service.solve(case, threads, args.timeout, args.metric,
                                            args.max_cost, args.incumbent_mode)
                        run["ready_capabilities"] = service.ready.get("assets")
                        output["tail_enabled"] = run["result"].get("tail_enabled")
                        run.update(variant=variant, repeat=repeat)
                        output["runs"].append(run)
                        print(
                            json.dumps(
                                {
                                    k: run[k]
                                    for k in ("case", "variant", "repeat", "threads", "wall_seconds", "completed_depth")
                                }
                            ),
                            flush=True,
                        )
                        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            finally:
                service.close()
    for variant in variants:
        for threads in map(int, args.threads.split(",")):
            for case in selected:
                runs = [
                    run
                    for run in output["runs"]
                    if run["variant"] == variant and run["threads"] == threads and run["case"] == case["name"]
                ]
                output["summaries"][f"{variant}/{threads}/{case['name']}"] = summary(runs)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
