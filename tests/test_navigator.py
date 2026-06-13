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
        self.annotations = []

    def screenshot(self):
        return np.zeros((540, 960, 3), dtype=np.uint8)

    def tap(self, x, y):
        self.taps.append((x, y))

    def annotate_next_tap_debug(self, *, lines=(), boxes=()):
        self.annotations.append((list(lines), list(boxes)))


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
        finder = FakeFinder(
            TaskSearchResult(
                TaskSearchStatus.READY,
                label_match=MatchResult(
                    template_path=Path("task_label_wide.png"),
                    confidence=0.98,
                    center=(330, 300),
                    bbox=(220, 288, 220, 24),
                ),
                go_match=_go_match(),
            )
        )
        navigator = Navigator(controller, FakeMatcher(), FakeDetector(), finder)

        result = navigator.open_task_from_daily(TASK_SPECS["guild_wish"])

        self.assertEqual(result.status, OpenTaskStatus.OPENED)
        self.assertEqual(controller.taps, [(840, 300)])
        self.assertEqual(len(controller.annotations), 1)
        lines, boxes = controller.annotations[0]
        self.assertIn("daily task: guild_wish", lines[0])
        self.assertTrue(any(box[-1] == "label_roi" for box in boxes))
        self.assertTrue(any(box[-1] == "label" for box in boxes))
        self.assertTrue(any(box[-1] == "status_roi" for box in boxes))
        self.assertTrue(any(box[-1] == "go" for box in boxes))
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

    def test_open_task_from_daily_scrolls_after_weak_done_candidate(self):
        controller = FakeController()
        finder = FakeFinder(
            TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                done_match=MatchResult(
                    template_path=Path("completed_button.png"),
                    confidence=0.95,
                    center=(840, 380),
                    bbox=(768, 360, 144, 40),
                ),
                weak_match=True,
                reason="weak task label found with completed button on the same row",
            ),
            TaskSearchResult(TaskSearchStatus.READY, go_match=_go_match()),
        )
        navigator = Navigator(controller, FakeMatcher(), FakeDetector(), finder)

        result = navigator.open_task_from_daily(TASK_SPECS["time_travel"])

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
