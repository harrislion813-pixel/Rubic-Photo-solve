"""Paired, complete exclusion-tree ablations for either isolated engine."""
from __future__ import annotations

import argparse
import json
import os
import queue
import statistics
import subprocess
import threading
import time
from pathlib import Path

from benchmark_isolation_short import fixed_layer, sha256
from benchmark_native import case_state, peak_memory
from cube_app.cubie import to_facelets

ROOT = Path(__file__).resolve().parents[1]
ORDER = (("baseline", "current"), ("current", "baseline"), ("baseline", "current"))
COUNTERS = ("generated_candidates", "small_queries", "phase1_queries", "corner_queries", "strong_queries",
            "axis_rejects", "equality_rejects", "corner_rejects", "strong_rejects", "edge_queries", "edge_rejects")
TREE_COUNTERS = ("generated_candidates", "axis_rejects", "equality_rejects", "corner_rejects", "strong_rejects", "edge_rejects")


class Service:
    def __init__(self, binary: Path, metric: str, extra: list[str]):
        assets = ROOT / f"assets/{metric.lower()}/v1"
        paths = [assets / name for name in ("corner_htm_v2.pdb", "phase1_sym_htm_v2.pdb", "tail_depth6_v4.pdb")]
        flags = ["--pdb", paths[0], "--phase1-pdb", paths[1], "--tail-pdb", paths[2]]
        if metric == "QTM":
            for flag, name in (("--qtm-pdb", "corner_qtm_v3.pdb"), ("--qtm-phase1-pdb", "phase1_qtm_v3.pdb"),
                               ("--strong-pdb", "strong_qtm_v4_nibble.pdb"), ("--qtm-tail-pdb", "tail_qtm_depth8_v5.pdb")):
                paths.append(assets / name)
                flags += [flag, paths[-1]]
            flags += ["--asset-loading=eager", "--no-proof-cache", "--no-native-candidate",
                      "--direction-policy=off", "--dual-policy=off", "--pdb-query-order=strong-first", "--loader-threads", "8"]
        self.command = list(map(str, [binary.resolve(), "serve", *flags, *extra]))
        self.paths = paths
        self.metric = metric
        self.errors = []
        self.lines = queue.Queue()
        env = os.environ.copy()
        env["CUBE_NATIVE_COORDINATE_CACHE"] = str(ROOT / f".cache/{metric.lower()}/" /
            ("coordinates_htm_v1.bin" if metric == "HTM" else "coordinates_dual_v2.bin"))
        started = time.perf_counter()
        self.process = subprocess.Popen(self.command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def read_output():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)
        def read_errors():
            self.errors.extend(self.process.stderr)
        threading.Thread(target=read_output, daemon=True).start()
        threading.Thread(target=read_errors, daemon=True).start()
        try:
            self.ready = self.event(60)
            if self.ready.get("type") != "ready" or not self.ready.get("ok"):
                raise RuntimeError(f"invalid ready: {self.ready}")
            if metric == "QTM" and self.ready.get("assets", {}).get("QTM", {}).get("profile") != "strong":
                raise RuntimeError(f"complete strong asset readiness missing: {self.ready}")
            self.startup_seconds = time.perf_counter() - started
        except BaseException:
            self.close()
            raise

    def event(self, timeout):
        line = self.lines.get(timeout=timeout)
        if line is None:
            raise RuntimeError("service exited: " + "".join(self.errors[-5:]))
        return json.loads(line)

    def solve(self, facelets, bound, timeout, threads, request_id):
        if self.metric == "QTM":
            fields = ["solve", request_id, facelets, str(bound), str(timeout), str(threads), "QTM", ""]
        else:
            # Legacy HTM framing bypasses its completed-proof reuse cache.
            fields = [facelets, str(bound), str(timeout), str(threads), ""]
        started = time.perf_counter()
        self.process.stdin.write("\t".join(fields) + "\n")
        self.process.stdin.flush()
        events = []
        while True:
            event = self.event(timeout + 10)
            if self.metric == "QTM" and event.get("request_id") != request_id:
                continue
            if event.get("type") in {"progress", "candidate", "asset_ready", "asset_adopted", "thread_activity", "strong_upgrade"}:
                events.append(event)
                continue
            run = {"bound": bound, "wall_seconds": time.perf_counter() - started, "result": event,
                   "progress": events, "peak_working_set_bytes": peak_memory(self.process)}
            return run

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metric", choices=("HTM", "QTM"), required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--baseline-extra", action="append", default=[])
    parser.add_argument("--current-extra", action="append", default=[])
    parser.add_argument("--pgo-bound", type=int, required=True)
    parser.add_argument("--known-bound", type=int, required=True)
    parser.add_argument("--case-a", default="pgo16")
    parser.add_argument("--case-b", default="known18")
    parser.add_argument("--threads", type=int, default=15)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error("thread quota must be 1..32")
    cases = {c["name"]: to_facelets(case_state(c)[0]) for c in
             json.loads((ROOT / "tests/native_cases.json").read_text(encoding="utf-8"))}
    report = {"metric": args.metric, "threads": args.threads, "timeout_seconds": 5,
              "search_budget_seconds": 60, "order": ORDER,
              "scope": "eager assets; no candidates, incumbent, direction changes or proof cache; warm OS file cache",
              "binaries": {}, "services": {}, "runs": [], "summary": {}, "failures": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    services = {}
    try:
        for label in ("baseline", "current"):
            binary = getattr(args, label)
            report["binaries"][label] = {"path": str(binary.resolve()), "sha256": sha256(binary)}
            services[label] = Service(binary, args.metric, getattr(args, f"{label}_extra"))
            s = services[label]
            report["services"][label] = {"command": s.command, "startup_seconds": s.startup_seconds, "ready": s.ready}
        report["assets"] = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in services["baseline"].paths}
        save()
        for repeat, labels in enumerate(ORDER):
            for name, bound in ((args.case_a, args.pgo_bound), (args.case_b, args.known_bound)):
                for label in labels:
                    run = services[label].solve(cases[name], bound, 5, args.threads, f"{label}-{name}-{repeat}")
                    run.update(binary=label, case=name, facelets=cases[name], repeat=repeat)
                    report["runs"].append(run)
                    save()
                    run["fixed_layer"] = fixed_layer(run)
                    if run["result"].get("candidate_phase1_nodes", 0) or run["result"].get("candidate_phase2_nodes", 0):
                        raise AssertionError("pure proof diagnostic ran candidate search")
                    print(json.dumps({k: run[k] for k in ("binary", "case", "repeat", "wall_seconds")}), flush=True)
        for name in (args.case_a, args.case_b):
            selected = [r for r in report["runs"] if r["case"] == name]
            frames = [r["progress"][-1] if r["result"].get("type") == "error" else r["result"] for r in selected]
            # Adaptive task splitting can add accepted task-entry heuristic
            # rechecks. Their query counts vary even between identical binaries;
            # generated nodes and all rejection counts still match exactly.
            for field in TREE_COUNTERS:
                if len({json.dumps(f.get(field), sort_keys=True) for f in frames}) != 1:
                    raise AssertionError(f"same-tree counter changed: {name}/{field}")
            medians = {label: statistics.median(r["wall_seconds"] for r in selected if r["binary"] == label)
                       for label in ("baseline", "current")}
            ratio = medians["current"] / medians["baseline"]
            report["summary"][name] = {"median_seconds": medians, "current_over_baseline": ratio,
                "generated_candidates": frames[0].get("generated_candidates"),
                "same_tree_counters": {key: frames[0].get(key) for key in TREE_COUNTERS},
                "query_counter_ranges": {key: [min(f.get(key, 0) or 0 for f in frames), max(f.get(key, 0) or 0 for f in frames)]
                                         for key in COUNTERS if key.endswith("queries")}}
        ratios = [s["current_over_baseline"] for s in report["summary"].values()]
        report["adopt"] = all(r <= 1.05 for r in ratios) and all(r <= 0.95 for r in ratios)
    except BaseException as error:
        report["failures"].append({"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        for label, service in services.items():
            service.close()
            report["services"][label]["stderr"] = service.errors
        save()
    print(json.dumps({"summary": report["summary"], "adopt": report["adopt"]}, indent=2))


if __name__ == "__main__":
    main()
