"""Wellness timer scheduler.

One repeating threading.Timer per enabled TimerConfig. All public methods
are thread-safe. stop() joins all worker threads so shutdown is clean.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from .config import TimerConfig


log = logging.getLogger(__name__)

GLOBAL_SNOOZE_SECONDS = 15 * 60


class _RepeatingTimer:
    """A self-rescheduling threading.Timer."""

    def __init__(self, interval_seconds: float, callback: Callable[[], None],
                 name: str):
        self._interval = interval_seconds
        self._callback = callback
        self._name = name
        self._timer: Optional[threading.Timer] = None
        self._stopped = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self._stopped.clear()
            self._schedule(self._interval)

    def _schedule(self, delay: float) -> None:
        if self._stopped.is_set():
            return
        t = threading.Timer(delay, self._fire)
        t.daemon = True
        t.name = f"WellnessTimer-{self._name}"
        self._timer = t
        t.start()

    def _fire(self) -> None:
        if self._stopped.is_set():
            return
        try:
            self._callback()
        except Exception:
            log.exception("Timer callback for %r raised", self._name)
        with self._lock:
            self._schedule(self._interval)

    def delay_next(self, seconds: float) -> None:
        """Cancel pending fire and reschedule after `seconds`."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._schedule(seconds)

    def stop(self) -> None:
        with self._lock:
            self._stopped.set()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class Scheduler:
    """Owns the active set of repeating timers."""

    def __init__(self, fire_callback: Callable[[TimerConfig], None]):
        self._fire = fire_callback
        self._timers: dict[str, _RepeatingTimer] = {}
        self._lock = threading.Lock()
        self._paused = False

    # ---- lifecycle ----------------------------------------------------

    def apply(self, timers: list[TimerConfig], global_enabled: bool) -> None:
        """Replace the entire timer set. Safe to call repeatedly."""
        self.stop()
        with self._lock:
            self._paused = not global_enabled
            if not global_enabled:
                return
            for cfg in timers:
                if not cfg.enabled:
                    continue
                self._start_one(cfg)

    def stop(self) -> None:
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
        for t in timers:
            t.stop()

    # ---- pause/snooze -------------------------------------------------

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            timers = list(self._timers.values())
            self._timers.clear()
        for t in timers:
            t.stop()

    def snooze_all(self, seconds: int = GLOBAL_SNOOZE_SECONDS) -> None:
        """Delay every active timer's next fire by `seconds`."""
        with self._lock:
            for t in self._timers.values():
                t.delay_next(seconds)

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    # ---- internal -----------------------------------------------------

    def _start_one(self, cfg: TimerConfig) -> None:
        interval_seconds = max(1, cfg.interval_minutes * 60)
        captured = cfg  # capture by closure

        def fire() -> None:
            self._fire(captured)

        timer = _RepeatingTimer(interval_seconds, fire, cfg.name)
        self._timers[cfg.name] = timer
        timer.start()
