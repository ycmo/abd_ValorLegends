from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional


_PROCESS_TIMER_STARTED = time.perf_counter()
_PROFILE_LOG_PATH: Optional[Path] = None
_PROFILE_LOCK = threading.RLock()


def configure_profile_log(path: Optional[Path]) -> None:
    global _PROFILE_LOG_PATH
    with _PROFILE_LOCK:
        _PROFILE_LOG_PATH = Path(path) if path is not None else None
        if _PROFILE_LOG_PATH is not None:
            _PROFILE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _active_profile_log_path() -> Optional[Path]:
    with _PROFILE_LOCK:
        if _PROFILE_LOG_PATH is not None:
            return _PROFILE_LOG_PATH
    env_path = os.environ.get("VL_PROFILE_LOG_FILE")
    return Path(env_path).expanduser() if env_path else None


def profile_enabled() -> bool:
    if os.environ.get("VL_PROFILE_LOADS", "").lower() in ("1", "true", "yes", "on"):
        return True
    return _active_profile_log_path() is not None


def profile_load(message: str) -> None:
    if not profile_enabled():
        return

    uptime = time.perf_counter() - _PROCESS_TIMER_STARTED
    line = f"[perf pid={os.getpid()} uptime={uptime:.3f}s] {message}"
    if os.environ.get("VL_PROFILE_LOADS", "").lower() in ("1", "true", "yes", "on"):
        print(line, flush=True)

    path = _active_profile_log_path()
    if path is None:
        return
    with _PROFILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
