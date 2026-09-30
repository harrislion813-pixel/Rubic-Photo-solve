"""Request-level CPU ownership; search and asset policy stay inside each engine."""

from __future__ import annotations

import threading
import time
import os
from collections.abc import Callable


class ResourceCancelled(RuntimeError):
    pass


class ResourceBroker:
    def __init__(self, threads: int | None = None) -> None:
        if threads is None:
            threads = min(32, max(1, (os.cpu_count() or 1) - 1))
        self.threads = max(1, threads)
        self._condition = threading.Condition()
        self._htm_holders = 0
        self._qtm_active = False
        self._qtm_cancel: threading.Event | None = None
        self._qtm_stop: Callable[[], None] | None = None
        self._qtm_resident_stop: Callable[[], None] | None = None
        self.last_yield_seconds = 0.0
        self.yield_faults = 0

    def enter_htm(self, deadline: float | None = None, cancel_event: threading.Event | None = None) -> float:
        started = time.monotonic()

        def check_budget() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise ResourceCancelled("HTM resource wait was cancelled")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("HTM resource wait exceeded the request deadline")

        check_budget()
        with self._condition:
            self._htm_holders += 1
            cancel = self._qtm_cancel
            stop = self._qtm_stop
            resident_stop = self._qtm_resident_stop
            self._qtm_resident_stop = None
            if cancel is not None:
                cancel.set()
        try:
            if resident_stop is not None:
                resident_stop()
            with self._condition:
                until = min(started + 1.0, deadline) if deadline is not None else started + 1.0
                while self._qtm_active and time.monotonic() < until:
                    check_budget()
                    self._condition.wait(timeout=min(0.05, max(0.0, until - time.monotonic())))
                check_budget()
                force = self._qtm_active
            if force and stop is not None:
                stop()
                with self._condition:
                    until = min(started + 2.0, deadline) if deadline is not None else started + 2.0
                    while self._qtm_active and time.monotonic() < until:
                        check_budget()
                        self._condition.wait(timeout=min(0.05, max(0.0, until - time.monotonic())))
                    check_budget()
                    if self._qtm_active:
                        self.yield_faults += 1
                        raise RuntimeError("QTM did not release its resources after cancellation")
            check_budget()
        except BaseException:
            self.leave_htm()
            raise
        self.last_yield_seconds = time.monotonic() - started
        return self.last_yield_seconds

    def leave_htm(self) -> None:
        with self._condition:
            self._htm_holders -= 1
            if self._htm_holders < 0:
                raise RuntimeError("unbalanced HTM resource release")
            self._condition.notify_all()

    def acquire_qtm(
        self,
        cancel: threading.Event,
        stop: Callable[[], None],
        deadline: float | None,
    ) -> bool:
        with self._condition:
            while self._htm_holders or self._qtm_active:
                if cancel.is_set() or (deadline is not None and time.monotonic() >= deadline):
                    return False
                self._condition.wait(timeout=0.05)
            if cancel.is_set() or (deadline is not None and time.monotonic() >= deadline):
                return False
            self._qtm_resident_stop = None
            self._qtm_active = True
            self._qtm_cancel = cancel
            self._qtm_stop = stop
            return True

    def release_qtm(self, resident_stop: Callable[[], None] | None = None) -> None:
        with self._condition:
            cleanup = resident_stop if self._htm_holders else None
            if cleanup is None:
                self._qtm_resident_stop = resident_stop
                self._qtm_active = False
                self._qtm_cancel = None
                self._qtm_stop = None
                self._condition.notify_all()
                return
        # An HTM claim may arrive while QTM is confirming its idle pause.
        # Keep the CPU lease held until this resident is completely gone.
        try:
            cleanup()
        except BaseException:
            with self._condition:
                self.yield_faults += 1
                self._qtm_stop = cleanup
            raise
        with self._condition:
            self._qtm_resident_stop = None
            self._qtm_active = False
            self._qtm_cancel = None
            self._qtm_stop = None
            self._condition.notify_all()

    def clear_qtm_resident(self, stop: Callable[[], None]) -> None:
        with self._condition:
            if self._qtm_resident_stop is stop:
                self._qtm_resident_stop = None
                self._condition.notify_all()

    def snapshot(self) -> dict:
        with self._condition:
            return {
                "threads": self.threads,
                "htm_holders": self._htm_holders,
                "qtm_active": self._qtm_active,
                "qtm_resident": self._qtm_resident_stop is not None,
                "last_yield_seconds": self.last_yield_seconds,
                "yield_faults": self.yield_faults,
            }


BROKER = ResourceBroker()
