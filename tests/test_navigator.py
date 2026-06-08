from pathlib import Path
from unittest import TestCase

import numpy as np

from src.config import TASK_SPECS
from src.daily_task_finder import TaskSearchResult, TaskSearchStatus
from src.navigator import Navigator, OpenTaskStatus
from src.scene_detector import Scene, SceneDetection
from src.vision_matcher import MatchResult


def _go_match() -> MatchResult:
    return MatchResult(
        template_path=Path("go_button.png"),
        confidence=0.95,
        center=(840, 300),
        bbox=(770, 280, 140, 40),
    )


class FakeController:
    def __init__(self):
        self.taps = []

    def screenshot(self):
        return np.zeros((540, 960, 3), dtype=np.uint8)

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeDetector:
    def detect(self, _screen):
        return SceneDetection(Scene.DAILY_TASKS, confidence=1.0)


class FakeFinder:
    def __init__(self, current_result, scroll_result=None):
        self.current_result = current_result
        self.scroll_result = scroll_result
        self.current_calls = 0
        self.scroll_calls = 0

    def find_on_current_screen(self, _spec):
        self.current_calls += 1
        return self.current_result

    def find_near_current_screen(self, _spec):
        self.current_calls += 1
        return self.current_result

    def scroll_to_task(self, _spec):
        self.scroll_calls += 1
        if self.scroll_result is None:
            raise AssertionError("scroll_to_task should not be called")
        return self.scroll_result


class FakeMatcher:
    pass


class NavigatorTaskOpenTests(TestCase):
    def test_open_task_from_daily_prefers_current_visible_row(self):
        controller = FakeController()
        finder = FakeFinder(TaskSearchResult(TaskSearchStatus.READY, go_match=_go_match()))
        navigator = Navigator(controller, FakeMatcher(), FakeDetector(), finder)

        result = navigator.open_task_from_daily(TASK_SPECS["guild_wish"])

        self.assertEqual(result.status, OpenTaskStatus.OPENED)
        self.assertEqual(controller.taps, [(840, 300)])
        self.assertEqual(finder.current_calls, 1)
        self.assertEqual(finder.scroll_calls, 0)

    def test_open_task_from_daily_scrolls_only_when_current_screen_misses(self):
        controller = FakeController()
        finder = FakeFinder(
            TaskSearchResult(TaskSearchStatus.NOT_FOUND, reason="not visible"),
            TaskSearchResult(TaskSearchStatus.READY, go_match=_go_match()),
        )
        navigator = Navigator(controller, FakeMatcher(), FakeDetector(), finder)

        result = navigator.open_task_from_daily(TASK_SPECS["guild_wish"])

        self.assertEqual(result.status, OpenTaskStatus.OPENED)
        self.assertEqual(controller.taps, [(840, 300)])
        self.assertEqual(finder.current_calls, 1)
        self.assertEqual(finder.scroll_calls, 1)

    def test_open_task_from_daily_skips_current_done_row_without_scrolling(self):
        controller = FakeController()
        finder = FakeFinder(
            TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                reason="task label found but Go button not found on the same row",
            )
        )
        navigator = Navigator(controller, FakeMatcher(), FakeDetector(), finder)

        result = navigator.open_task_from_daily(TASK_SPECS["guild_wish"])

        self.assertEqual(result.status, OpenTaskStatus.SKIPPED_DONE_OR_CLAIMABLE)
        self.assertEqual(controller.taps, [])
        self.assertEqual(finder.current_calls, 1)
        self.assertEqual(finder.scroll_calls, 0)
