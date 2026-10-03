"""Observe one launched Windows process tree through OS counters, without HTTP."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
from ctypes import wintypes


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent_pid", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                ("name", wintypes.WCHAR * 260)]


class Counters(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ("peak_ws", "working_set", "peak_paged", "paged",
                                           "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]


def observe(root_pid: int, output: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("the fixed reference-machine memory gate requires Windows OS peak counters")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handles = {}
    records = {}
    known = {root_pid}
    samples = []
    stop = threading.Event()
    started = time.perf_counter()

    def read_stop():
        for line in sys.stdin:
            if line.strip() == "stop":
                break
        stop.set()

    threading.Thread(target=read_stop, daemon=True).start()
    print(json.dumps({"ready": True, "root_pid": root_pid, "interval_seconds": 0.5}), flush=True)
    try:
        finishing = False
        while True:
            snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
            if snapshot == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                entry = ProcessEntry()
                entry.size = ctypes.sizeof(entry)
                listing = {}
                success = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
                while success:
                    listing[entry.pid] = {"parent_pid": entry.parent_pid, "name": entry.name}
                    success = kernel.Process32NextW(snapshot, ctypes.byref(entry))
            finally:
                kernel.CloseHandle(snapshot)
            changed = True
            while changed:
                previous = len(known)
                known.update(pid for pid, item in listing.items() if item["parent_pid"] in known)
                changed = len(known) != previous
            for pid in known:
                if pid not in handles and pid in listing:
                    handle = kernel.OpenProcess(0x410, False, pid)
                    if handle:
                        handles[pid] = handle
                        records[pid] = {"pid": pid, **listing[pid], "peak_working_set_bytes": 0,
                                        "observed_samples": 0}
            working_set = 0
            for pid, handle in handles.items():
                exit_code = wintypes.DWORD()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
                    continue
                counters = Counters()
                counters.size = ctypes.sizeof(counters)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.size):
                    record = records[pid]
                    record["peak_working_set_bytes"] = max(record["peak_working_set_bytes"], counters.peak_ws)
                    record["observed_samples"] += 1
                    record["last_sample_seconds"] = time.perf_counter() - started
                    working_set += counters.working_set
            samples.append({"seconds": time.perf_counter() - started, "working_set_bytes": working_set})
            if finishing:
                samples[-1]["final"] = True
                break
            if stop.wait(0.5):
                # Take one last OS sample while resident native processes are
                # still alive; the runner stops this observer before taskkill.
                finishing = True
    finally:
        for handle in handles.values():
            kernel.CloseHandle(handle)
        native = [record for record in records.values() if record["name"].lower() in
                  {"cube_solver_htm.exe", "cube_solver_qtm.exe"}]
        result = {"root_pid": root_pid, "interval_seconds": 0.5,
                  "scope": "launcher_descendant_native_process_lifetime_peak",
                  "native_process_lifetime_peak_bytes": max((r["peak_working_set_bytes"] for r in native), default=None),
                  "tree_sampled_peak_working_set_bytes": max((s["working_set_bytes"] for s in samples), default=None),
                  "tree_scope": "launcher_process_tree_observed_working_set_sum_at_0.5_second_intervals",
                  "processes": list(records.values()), "samples": samples}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    observe(args.root_pid, args.output)


if __name__ == "__main__":
    main()
