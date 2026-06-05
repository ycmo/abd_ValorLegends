from __future__ import annotations

from pathlib import Path
from unittest import TestCase

import numpy as np

from src.config import TASK_SPECS
from src.daily_task_finder import DailyTaskFinder, TaskSearchStatus
from src.vision_matcher import MatchResult


class FakeController:
    def __init__(self):
        self.screen = np.zeros((540, 960, 3), dtype=np.uint8)
        self.swipes = []

    def screenshot(self):
        return self.screen

    def swipe(self, x1, y1, x2, y2, duration_ms):
        self.swipes.append((x1, y1, x2, y2, duration_ms))


class FakeMatcher:
    def __init__(self, label: MatchResult, go: MatchResult | None = None):
        self.label = label
        self.go = go
        self.calls = []

    def match_template(self, screen, template_path: Path, threshold=0.0, roi=None):
        self.calls.append((template_path.name, threshold, roi))
        if template_path.name == "task_label.png":
            return self.label
        if template_path.name == "go_button.png":
            return self.go
        return None


def _label_at(y: int) -> MatchResult:
    return MatchResult(
        template_path=Path("task_label.png"),
        confidence=0.90,
        center=(330, y),
        bbox=(228, y - 11, 205, 22),
    )


class DailyTaskFinderTests(TestCase):
    def test_bottom_edge_row_is_not_classified_done(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(502), go=None))

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.NOT_FOUND)
        self.assertIn("bottom edge", result.reason)
        self.assertIsNotNone(result.label_match)

    def test_missing_go_on_safe_visible_row_is_done_or_claimable(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(430), go=None))

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.DONE_OR_CLAIMABLE)
        self.assertIn("Go button not found", result.reason)
