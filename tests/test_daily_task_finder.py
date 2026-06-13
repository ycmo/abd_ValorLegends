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
    def __init__(
        self,
        label: MatchResult | None,
        go: MatchResult | None = None,
        claim: MatchResult | None = None,
        done: MatchResult | None = None,
        labels_by_name: dict[str, MatchResult | None] | None = None,
    ):
        self.label = label
        self.go = go
        self.claim = claim
        self.done = done
        self.labels_by_name = labels_by_name or {}
        self.calls = []

    def match_template(self, screen, template_path: Path, threshold=0.0, roi=None, check_brightness=True):
        self.calls.append((template_path.name, threshold, roi))
        if template_path.name in self.labels_by_name:
            return self.labels_by_name[template_path.name]
        if template_path.name == "task_label.png":
            return self.label
        if template_path.name == "go_button.png":
            return self.go
        if template_path.name == "claim_button.png":
            return self.claim
        if template_path.name == "completed_button.png":
            return self.done
        return None

    def match_any(self, screen, template_paths, threshold=0.0, roi=None, check_brightness=True):
        best = None
        for template_path in template_paths:
            result = self.match_template(
                screen,
                template_path,
                threshold=threshold,
                roi=roi,
                check_brightness=check_brightness,
            )
            if result is None:
                continue
            if best is None or result.confidence > best.confidence:
                best = result
        return best


def _label_at(y: int) -> MatchResult:
    return MatchResult(
        template_path=Path("task_label.png"),
        confidence=0.90,
        center=(330, y),
        bbox=(228, y - 11, 205, 22),
    )


def _wide_label_at(y: int) -> MatchResult:
    return MatchResult(
        template_path=Path("task_label_wide.png"),
        confidence=0.92,
        center=(330, y),
        bbox=(218, y - 21, 225, 42),
    )


def _go_at(y: int) -> MatchResult:
    return MatchResult(
        template_path=Path("go_button.png"),
        confidence=0.95,
        center=(840, y),
        bbox=(768, y - 20, 144, 40),
    )


def _done_at(y: int) -> MatchResult:
    return MatchResult(
        template_path=Path("completed_button.png"),
        confidence=0.91,
        center=(840, y),
        bbox=(768, y - 20, 144, 40),
    )


def _claim_at(y: int) -> MatchResult:
    return MatchResult(
        template_path=Path("claim_button.png"),
        confidence=0.91,
        center=(840, y),
        bbox=(768, y - 20, 144, 40),
    )


class DailyTaskFinderTests(TestCase):
    def test_daily_task_rois_match_reviewed_960x540_regions(self):
        label_roi = DailyTaskFinder._task_list_roi(960, 540)
        go_roi = DailyTaskFinder._same_row_right_roi(960, 540, _wide_label_at(336))

        self.assertEqual(label_roi, (216, 211, 253, 325))
        self.assertEqual(go_roi, (744, 301, 191, 100))

    def test_bottom_edge_row_is_not_classified_done(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(502), go=None))

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.NOT_FOUND)
        self.assertIn("bottom edge", result.reason)
        self.assertIsNotNone(result.label_match)

    def test_bottom_edge_row_with_go_button_is_ready(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(502), go=_go_at(475)))

        result = finder.find_on_current_screen(TASK_SPECS["secret_realm"])

        self.assertEqual(result.status, TaskSearchStatus.READY)
        self.assertIsNotNone(result.go_match)

    def test_missing_go_on_safe_visible_row_is_done_or_claimable(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(430), go=None))

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.DONE_OR_CLAIMABLE)
        self.assertIn("Go button not found", result.reason)

    def test_completed_button_on_same_row_is_done_or_claimable(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(430), go=None, done=_done_at(430)))

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.DONE_OR_CLAIMABLE)
        self.assertEqual(result.done_match.template_path.name, "completed_button.png")
        self.assertIn("completed button", result.reason)

    def test_claim_button_on_same_row_is_done_or_claimable(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(430), go=None, claim=_claim_at(430)))

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.DONE_OR_CLAIMABLE)
        self.assertEqual(result.claim_match.template_path.name, "claim_button.png")
        self.assertIn("claim button", result.reason)

    def test_weak_label_with_completed_button_is_done_or_claimable(self):
        weak = MatchResult(
            template_path=Path("task_label_wide.png"),
            confidence=0.62,
            center=(330, 430),
            bbox=(218, 409, 225, 42),
        )
        matcher = FakeMatcher(
            label=None,
            done=_done_at(430),
            labels_by_name={"task_label_wide.png": weak},
        )
        finder = DailyTaskFinder(FakeController(), matcher)

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.DONE_OR_CLAIMABLE)
        self.assertEqual(result.label_match.template_path.name, "task_label_wide.png")
        self.assertEqual(result.done_match.template_path.name, "completed_button.png")

    def test_weak_label_with_claim_button_is_done_or_claimable(self):
        weak = MatchResult(
            template_path=Path("task_label_wide.png"),
            confidence=0.62,
            center=(330, 430),
            bbox=(218, 409, 225, 42),
        )
        matcher = FakeMatcher(
            label=None,
            claim=_claim_at(430),
            labels_by_name={"task_label_wide.png": weak},
        )
        finder = DailyTaskFinder(FakeController(), matcher)

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.DONE_OR_CLAIMABLE)
        self.assertEqual(result.label_match.template_path.name, "task_label_wide.png")
        self.assertEqual(result.claim_match.template_path.name, "claim_button.png")

    def test_weak_label_with_go_button_is_ready_before_completed_fallback(self):
        weak = MatchResult(
            template_path=Path("task_label_wide.png"),
            confidence=0.62,
            center=(330, 430),
            bbox=(218, 409, 225, 42),
        )
        matcher = FakeMatcher(
            label=None,
            go=_go_at(430),
            claim=_claim_at(430),
            done=_done_at(430),
            labels_by_name={"task_label_wide.png": weak},
        )
        finder = DailyTaskFinder(FakeController(), matcher)

        result = finder.find_on_current_screen(TASK_SPECS["time_travel"])

        self.assertEqual(result.status, TaskSearchStatus.READY)
        self.assertEqual(result.label_match.template_path.name, "task_label_wide.png")
        self.assertEqual(result.go_match.template_path.name, "go_button.png")
        self.assertIsNone(result.claim_match)
        self.assertIsNone(result.done_match)

    def test_wide_task_label_candidate_can_find_row(self):
        matcher = FakeMatcher(
            label=None,
            go=_go_at(430),
            labels_by_name={"task_label_wide.png": _wide_label_at(430)},
        )
        finder = DailyTaskFinder(FakeController(), matcher)

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.READY)
        self.assertEqual(result.label_match.template_path.name, "task_label_wide.png")
