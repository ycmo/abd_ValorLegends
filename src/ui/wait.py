from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from src.exceptions import BotError
from src.ui.blockers import BLOCKER_POLICY_SAFE


BLOCKER_PHASE_BEFORE_PREDICATE = "before_predicate"
BLOCKER_PHASE_AFTER_MISS = "after_miss"
BLOCKER_PHASES = {
    BLOCKER_PHASE_BEFORE_PREDICATE,
    BLOCKER_PHASE_AFTER_MISS,
}


@dataclass(frozen=True)
class ScreenWaitDecision:
    matched: bool
    value: Any = None
    sleep_seconds: Optional[float] = None
    allow_blocker: bool = True

    @classmethod
    def found(cls, value: Any = True) -> "ScreenWaitDecision":
        return cls(matched=True, value=value)

    @classmethod
    def retry(
        cls,
        *,
        sleep_seconds: Optional[float] = None,
        allow_blocker: bool = True,
    ) -> "ScreenWaitDecision":
        return cls(matched=False, sleep_seconds=sleep_seconds, allow_blocker=allow_blocker)


@dataclass(frozen=True)
class ScreenWaitResult:
    matched: bool
    value: Any = None
    screen: Optional[np.ndarray] = None
    attempts: int = 0
    elapsed_seconds: float = 0.0
    blockers_cleared: int = 0
    last_error: Optional[Exception] = None


Predicate = Callable[[np.ndarray, int], Any]
LogFn = Callable[[str], None]
TimeoutFn = Callable[[np.ndarray], None]
SleepFn = Callable[[float], None]
ClockFn = Callable[[], float]


def wait_for_screen(
    controller,
    predicate: Predicate,
    *,
    label: str,
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
    poll_seconds: float = 1.0,
    blocker=None,
    blocker_policy: str = BLOCKER_POLICY_SAFE,
    blocker_phase: str = BLOCKER_PHASE_AFTER_MISS,
    blocker_sleep_seconds: float = 0.5,
    screenshot_error_retries: int = 1,
    screenshot_error_sleep_seconds: float = 1.0,
    on_timeout: Optional[TimeoutFn] = None,
    log: Optional[LogFn] = None,
    sleeper: SleepFn = time.sleep,
    clock: ClockFn = time.monotonic,
) -> ScreenWaitResult:
    """Poll screenshots until a predicate reports success.

    This helper owns wait mechanics only: screenshot acquisition, optional safe
    blocker handling, retry sleeps, and timeout diagnostics. Callers keep the
    screen-specific meaning inside their predicate.
    """
    if timeout_seconds is None and max_attempts is None:
        raise ValueError("timeout_seconds or max_attempts is required")
    if max_attempts is not None and max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if timeout_seconds is not None and timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    if blocker_phase not in BLOCKER_PHASES:
        raise ValueError(f"unknown blocker phase: {blocker_phase!r}")

    start = clock()
    deadline = None if timeout_seconds is None else start + timeout_seconds
    attempts = 0
    blockers_cleared = 0
    last_screen = None
    last_error: Exception | None = None
    consecutive_screenshot_errors = 0

    while True:
        if max_attempts is not None and attempts >= max_attempts:
            break
        if deadline is not None and attempts > 0 and clock() >= deadline:
            break

        attempts += 1
        try:
            screen = controller.screenshot()
            consecutive_screenshot_errors = 0
        except BotError as exc:
            last_error = exc
            consecutive_screenshot_errors += 1
            if consecutive_screenshot_errors > screenshot_error_retries:
                raise
            _log(log, f"[Wait] {label}: screenshot failed; retrying ({exc})")
            _sleep(sleeper, screenshot_error_sleep_seconds)
            continue

        last_screen = screen

        if (
            blocker is not None
            and blocker_phase == BLOCKER_PHASE_BEFORE_PREDICATE
            and _handle_blocker(blocker, screen, blocker_policy)
        ):
            blockers_cleared += 1
            _log(log, f"[Wait] {label}: cleared blocker before predicate")
            _sleep(sleeper, blocker_sleep_seconds)
            continue

        decision = _coerce_decision(predicate(screen, attempts))
        if decision.matched:
            return ScreenWaitResult(
                matched=True,
                value=decision.value,
                screen=screen,
                attempts=attempts,
                elapsed_seconds=clock() - start,
                blockers_cleared=blockers_cleared,
                last_error=last_error,
            )

        if (
            blocker is not None
            and blocker_phase == BLOCKER_PHASE_AFTER_MISS
            and decision.allow_blocker
            and _handle_blocker(blocker, screen, blocker_policy)
        ):
            blockers_cleared += 1
            _log(log, f"[Wait] {label}: cleared blocker after miss")
            _sleep(sleeper, blocker_sleep_seconds)
            continue

        sleep_seconds = poll_seconds if decision.sleep_seconds is None else decision.sleep_seconds
        _sleep(sleeper, sleep_seconds)

    if on_timeout is not None and last_screen is not None:
        on_timeout(last_screen)

    return ScreenWaitResult(
        matched=False,
        screen=last_screen,
        attempts=attempts,
        elapsed_seconds=clock() - start,
        blockers_cleared=blockers_cleared,
        last_error=last_error,
    )


def _coerce_decision(value: Any) -> ScreenWaitDecision:
    if isinstance(value, ScreenWaitDecision):
        return value
    if value:
        return ScreenWaitDecision.found(value)
    return ScreenWaitDecision.retry()


def _handle_blocker(blocker, screen: np.ndarray, policy: str) -> bool:
    try:
        return bool(blocker.handle_known_blocker(screen, policy=policy))
    except TypeError:
        return bool(blocker.handle_known_blocker(screen))


def _sleep(sleeper: SleepFn, seconds: float) -> None:
    if seconds > 0:
        sleeper(seconds)


def _log(log: Optional[LogFn], message: str) -> None:
    if log is not None:
        log(message)


__all__ = [
    "BLOCKER_PHASE_AFTER_MISS",
    "BLOCKER_PHASE_BEFORE_PREDICATE",
    "ScreenWaitDecision",
    "ScreenWaitResult",
    "wait_for_screen",
]
