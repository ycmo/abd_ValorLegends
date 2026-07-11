from __future__ import annotations

import time
from collections.abc import Callable
from typing import Optional


Clock = Callable[[], float]
Sleeper = Callable[[float], None]


def sleep_until(
    deadline_seconds: float,
    *,
    interval_seconds: float = 10.0,
    clock: Optional[Clock] = None,
    sleeper: Optional[Sleeper] = None,
) -> None:
    """Sleep until a wall-clock deadline.

    Windows suspends Python while the computer sleeps. Using wall time means the
    first check after wake sees that the deadline already passed and returns.
    """
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")

    clock = clock or time.time
    sleeper = sleeper or time.sleep
    while True:
        remaining = deadline_seconds - clock()
        if remaining <= 0:
            return
        sleeper(min(interval_seconds, remaining))


def smart_sleep(
    delay_seconds: float,
    interval_seconds: float = 10.0,
    *,
    clock: Optional[Clock] = None,
    sleeper: Optional[Sleeper] = None,
) -> None:
    """Sleep for a delay using a wall-clock deadline.

    Use this for long AFK waits that should catch up after computer sleep.
    Keep short UI-transition waits on plain time.sleep.
    """
    if delay_seconds <= 0:
        return
    clock = clock or time.time
    sleep_until(
        clock() + delay_seconds,
        interval_seconds=interval_seconds,
        clock=clock,
        sleeper=sleeper,
    )
