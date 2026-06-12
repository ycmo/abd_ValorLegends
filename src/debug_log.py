from __future__ import annotations

import time


class DebugLogger:
    def __init__(self, enabled: bool = False, min_interval_seconds: float = 2.5):
        self.enabled = enabled
        self.started = time.time()
        self.min_interval_seconds = min_interval_seconds
        self._last_printed_at = 0.0

    def log(self, message: str, *, force: bool = False) -> None:
        if not self.enabled:
            return
        elapsed = time.time() - self.started
        if not force and self._last_printed_at and elapsed - self._last_printed_at < self.min_interval_seconds:
            return
        self._last_printed_at = elapsed
        print(f"[debug {elapsed:7.1f}s] {message}", flush=True)
