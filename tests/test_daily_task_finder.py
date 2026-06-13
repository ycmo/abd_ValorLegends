from __future__ import annotations

from pathlib import Path
from unittest import TestCase

import numpy as np

from src.config import TASK_SPECS
from src.daily_task_finder import DailyTaskFinder, TaskSearchResult, TaskSearchStatus
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
        result = None
        if template_path.name in self.labels_by_name:
            result = self.labels_by_name[template_path.name]
        elif template_path.name == "task_label.png":
            result = self.label
        elif template_path.name == "go_button.png":
            result = self.go
        elif template_path.name == "claim_button.png":
            result = self.claim
        elif template_path.name == "completed_button.png":
            result = self.done
        if result is not None and result.confidence < threshold:
            return None
        return result

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


class ScriptedFinder(DailyTaskFinder):
    def __init__(self, results: list[TaskSearchResult], swipe_results: list[bool] | None = None):
        self.results = list(results)
        self.swipe_results = list(swipe_results or [])
        self.swipes = 0
        self.reset_calls = 0

    def find_on_current_screen(self, spec):
        if not self.results:
            raise AssertionError("No scripted search result left")
        return self.results.pop(0)

    def _scroll_to_top(self, swipes: int) -> None:
        self.reset_calls += 1

    def _swipe_until_changed(self, *args, **kwargs) -> bool:
        self.swipes += 1
        if self.swipe_results:
            return self.swipe_results.pop(0)
        return True


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
        self.assertIn("done status button", result.reason)

    def test_claim_button_on_same_row_is_done_or_claimable(self):
        finder = DailyTaskFinder(FakeController(), FakeMatcher(_label_at(430), go=None, claim=_claim_at(430)))

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.DONE_OR_CLAIMABLE)
        self.assertEqual(result.claim_match.template_path.name, "claim_button.png")
        self.assertIn("done status button", result.reason)

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
        self.assertTrue(result.weak_match)

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
        self.assertTrue(result.weak_match)

    def test_weak_label_with_go_button_is_not_ready(self):
        weak = MatchResult(
            template_path=Path("task_label_wide.png"),
            confidence=0.62,
            center=(330, 430),
            bbox=(218, 409, 225, 42),
        )
        matcher = FakeMatcher(
            label=None,
            go=_go_at(430),
            labels_by_name={"task_label_wide.png": weak},
        )
        finder = DailyTaskFinder(FakeController(), matcher)

        result = finder.find_on_current_screen(TASK_SPECS["time_travel"])

        self.assertEqual(result.status, TaskSearchStatus.NOT_FOUND)
        self.assertIsNone(result.label_match)
        self.assertIsNone(result.go_match)
        self.assertIsNone(result.claim_match)
        self.assertIsNone(result.done_match)

    def test_low_confidence_label_with_go_button_is_not_ready(self):
        low_confidence = MatchResult(
            template_path=Path("task_label_wide.png"),
            confidence=0.80,
            center=(330, 385),
            bbox=(218, 374, 216, 22),
        )
        matcher = FakeMatcher(
            label=None,
            go=_go_at(385),
            labels_by_name={"task_label_wide.png": low_confidence},
        )
        finder = DailyTaskFinder(FakeController(), matcher)

        result = finder.find_on_current_screen(TASK_SPECS["arena"])

        self.assertEqual(result.status, TaskSearchStatus.NOT_FOUND)
        self.assertIsNone(result.go_match)

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

    def test_scroll_to_task_prefers_ready_after_weak_done_candidate(self):
        weak_done = TaskSearchResult(
            TaskSearchStatus.DONE_OR_CLAIMABLE,
            label_match=_wide_label_at(360),
            done_match=_done_at(360),
            weak_match=True,
            reason="weak task label found with done status button on the same row",
        )
        ready = TaskSearchResult(
            TaskSearchStatus.READY,
            label_match=_label_at(340),
            go_match=_go_at(340),
        )
        finder = ScriptedFinder([weak_done, ready])

        result = finder.scroll_to_task(TASK_SPECS["time_travel"])

        self.assertEqual(result.status, TaskSearchStatus.READY)
        self.assertEqual(result.go_match.template_path.name, "go_button.png")
        self.assertEqual(finder.swipes, 1)

    def test_scroll_to_task_returns_weak_done_only_after_list_bottom(self):
        weak_done = TaskSearchResult(
            TaskSearchStatus.DONE_OR_CLAIMABLE,
            label_match=_wide_label_at(360),
            done_match=_done_at(360),
            weak_match=True,
            reason="weak task label found with done status button on the same row",
        )
        finder = ScriptedFinder([weak_done], swipe_results=[False])

        result = finder.scroll_to_task(TASK_SPECS["time_travel"])

        self.assertEqual(result, weak_done)
