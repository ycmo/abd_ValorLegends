from __future__ import annotations

import unittest

from src.exceptions import BotError
from src.ui.blockers import BLOCKER_POLICY_SAFE
from src.ui.wait import (
    BLOCKER_PHASE_AFTER_MISS,
    BLOCKER_PHASE_BEFORE_PREDICATE,
    ScreenWaitDecision,
    wait_for_screen,
)


class FakeController:
    def __init__(self, screens):
        self.screens = list(screens)
        self.calls = 0

    def screenshot(self):
        self.calls += 1
        value = self.screens.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeBlocker:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def handle_known_blocker(self, screen, *, policy=BLOCKER_POLICY_SAFE):
        self.calls.append((screen, policy))
        if not self.results:
            return False
        return self.results.pop(0)


class ScreenWaitTests(unittest.TestCase):
    def test_wait_returns_predicate_match(self):
        controller = FakeController(["ready"])

        result = wait_for_screen(
            controller,
            lambda screen, attempt: ScreenWaitDecision.found((screen, attempt)),
            label="unit",
            max_attempts=3,
            sleeper=lambda _seconds: None,
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.value, ("ready", 1))
        self.assertEqual(result.attempts, 1)

    def test_wait_clears_blocker_after_predicate_miss(self):
        controller = FakeController(["blocked", "ready"])
        blocker = FakeBlocker([True])
        sleeps = []

        def predicate(screen, _attempt):
            if screen == "ready":
                return "ok"
            return None

        result = wait_for_screen(
            controller,
            predicate,
            label="unit",
            max_attempts=3,
            blocker=blocker,
            blocker_phase=BLOCKER_PHASE_AFTER_MISS,
            sleeper=sleeps.append,
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.value, "ok")
        self.assertEqual(result.blockers_cleared, 1)
        self.assertEqual(blocker.calls, [("blocked", BLOCKER_POLICY_SAFE)])
        self.assertEqual(sleeps, [0.5])

    def test_before_predicate_blocker_skips_predicate_for_blocked_screen(self):
        controller = FakeController(["blocked", "ready"])
        blocker = FakeBlocker([True, False])
        seen = []

        def predicate(screen, _attempt):
            seen.append(screen)
            return screen == "ready"

        result = wait_for_screen(
            controller,
            predicate,
            label="unit",
            max_attempts=3,
            blocker=blocker,
            blocker_phase=BLOCKER_PHASE_BEFORE_PREDICATE,
            sleeper=lambda _seconds: None,
        )

        self.assertTrue(result.matched)
        self.assertEqual(seen, ["ready"])

    def test_retry_can_skip_after_miss_blocker_on_action_screen(self):
        controller = FakeController(["action", "ready"])
        blocker = FakeBlocker([True])
        seen = []

        def predicate(screen, _attempt):
            seen.append(screen)
            if screen == "action":
                return ScreenWaitDecision.retry(sleep_seconds=0.0, allow_blocker=False)
            return True

        result = wait_for_screen(
            controller,
            predicate,
            label="unit",
            max_attempts=3,
            blocker=blocker,
            blocker_phase=BLOCKER_PHASE_AFTER_MISS,
            sleeper=lambda _seconds: None,
        )

        self.assertTrue(result.matched)
        self.assertEqual(seen, ["action", "ready"])
        self.assertEqual(blocker.calls, [])

    def test_screenshot_error_retries_once(self):
        controller = FakeController([BotError("adb wobble"), "ready"])
        sleeps = []

        result = wait_for_screen(
            controller,
            lambda screen, _attempt: screen == "ready",
            label="unit",
            max_attempts=3,
            screenshot_error_retries=1,
            screenshot_error_sleep_seconds=0.25,
            sleeper=sleeps.append,
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [0.25])


if __name__ == "__main__":
    unittest.main()
