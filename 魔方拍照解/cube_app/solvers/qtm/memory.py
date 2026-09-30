"""Admission samples include file-backed working set and private allocation."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path


def sample_memory(pid: int) -> dict | None:
    try:
        if os.name == 'nt':
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('peak_ws', 'working_set', 'peak_paged', 'paged',
                                                       'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
            class Status(ctypes.Structure):
                _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in ('total', 'available', 'total_page', 'available_page',
                                                          'total_virtual', 'available_virtual', 'extended')]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            handle = kernel.OpenProcess(0x410, False, pid)
            if not handle:
                return None
            try:
                counters = Counters()
                counters.cb = ctypes.sizeof(counters)
                status = Status()
                status.length = ctypes.sizeof(status)
                if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    return None
                if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
                    return None
                return {'working_set': counters.working_set, 'private_bytes': counters.private,
                        'available_bytes': status.available, 'total_bytes': status.total}
            finally:
                kernel.CloseHandle(handle)
        values = {}
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith(('VmRSS:', 'VmData:')):
                values[line.split(':')[0]] = int(line.split()[1]) * 1024
        info = dict((line.split(':')[0], int(line.split()[1])*1024)
                    for line in Path('/proc/meminfo').read_text().splitlines())
        return {'working_set': values['VmRSS'], 'private_bytes': values['VmData'],
                'available_bytes': info['MemAvailable'], 'total_bytes': info['MemTotal']}
    except (OSError, ValueError, KeyError):
        return None


def within_limit(sample: dict | None, limit: int, reserve: int) -> bool:
    return bool(sample and max(sample['working_set'], sample['private_bytes']) <= limit
                and sample['available_bytes'] >= reserve)
