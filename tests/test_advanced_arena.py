from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2

from src.exceptions import TaskFailedError
from src.tasks.advanced_arena import AdvancedArenaTask, parse_season_days
from src.vision_matcher import MatchResult, VisionMatcher, read_image


class FakeController:
    def __init__(self):
        self.taps = []
        self.annotations = []
        self.debug_saves = []

    def screenshot(self):
        return "screen"

    def tap(self, x, y):
        self.taps.append((x, y))

    def annotate_next_tap_debug(self, **kwargs):
        self.annotations.append(kwargs)

    def save_annotated_debug(self, *args, **kwargs):
        self.debug_saves.append((args, kwargs))


class FakeMatcher:
    def __init__(self, *, sequences=None, matches=None):
        self.sequences = {name: list(values) for name, values in (sequences or {}).items()}
        self.matches = matches or {}

    def match_template(self, _screen, path, **_kwargs):
        values = self.sequences.get(path.name)
        if values:
            return values.pop(0)
        return self.matches.get(path.name)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, message, *, force=False):
        self.messages.append(message)


class AdvancedArenaTests(unittest.TestCase):
    def test_parse_season_days(self):
        self.assertEqual(parse_season_days("9天18小時"), 9)
        self.assertEqual(parse_season_days("賽季重置倒數計時0天23小時"), 0)
        self.assertEqual(parse_season_days("18小時"), 0)
        self.assertEqual(parse_season_days("23"), 0)
        self.assertEqual(parse_season_days("24"), 0)
        self.assertEqual(parse_season_days("14"), 0)
        self.assertEqual(parse_season_days("8"), 0)
        self.assertEqual(parse_season_days("24時"), 0)
        self.assertEqual(parse_season_days("9 18"), 9)
        self.assertEqual(parse_season_days("918"), 9)
        self.assertEqual(parse_season_days("10 18"), 10)
        self.assertEqual(parse_season_days("1018"), 10)

    def test_execute_fails_and_returns_on_last_day(self):
        controller = FakeController()
        task = AdvancedArenaTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(),
                logger=FakeLogger(),
            )
        )

        with patch.object(task, "_read_season_days_or_fail", return_value=0), \
             patch("src.tasks.advanced_arena.time.sleep"):
            with self.assertRaises(TaskFailedError):
                task.execute()

        self.assertEqual(controller.taps, [AdvancedArenaTask.BACK_POINT])

    def test_execute_uses_three_free_tickets(self):
        controller = FakeController()
        task = AdvancedArenaTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "free_button.png": _match("free_button.png", 640, 326),
                    },
                ),
                logger=FakeLogger(),
            )
        )

        with patch.object(task, "_read_season_days_or_fail", return_value=9), \
             patch.object(task, "_open_challenge_dialog", return_value=True), \
             patch.object(task, "_ensure_skip_formation_selected", return_value=True), \
             patch.object(task, "_settle_battle_result"), \
             patch("src.tasks.advanced_arena.time.sleep"):
            message = task.execute()

        self.assertIn("free fights=3", message)
        self.assertEqual(controller.taps, [(640, 326), (640, 326), (640, 326)])

    def test_no_free_button_closes_dialog_and_stops(self):
        controller = FakeController()
        task = AdvancedArenaTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "challenge_dialog_close_button.png": _match("challenge_dialog_close_button.png", 716, 99),
                    },
                ),
                logger=FakeLogger(),
            )
        )

        with patch.object(task, "_read_season_days_or_fail", return_value=9), \
             patch.object(task, "_open_challenge_dialog", return_value=True), \
             patch.object(task, "_ensure_skip_formation_selected", return_value=True), \
             patch("src.tasks.advanced_arena.time.sleep"):
            message = task.execute()

        self.assertIn("free fights=0", message)
        self.assertEqual(controller.taps, [AdvancedArenaTask.POPUP_CLOSE_POINT])

    def test_open_challenge_dialog_accepts_no_free_state_with_close_button(self):
        controller = FakeController()
        task = AdvancedArenaTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "challenge_button.png": _match("challenge_button.png", 646, 501),
                        "challenge_dialog_close_button.png": _match("challenge_dialog_close_button.png", 716, 99),
                    },
                ),
                logger=FakeLogger(),
            )
        )

        with patch("src.tasks.advanced_arena.time.sleep"):
            self.assertTrue(task._open_challenge_dialog())

        self.assertEqual(controller.taps, [(646, 501)])

    def test_templates_match_manual_screenshots(self):
        matcher = VisionMatcher()
        manual_dir = Path("manual_screenshots") / "\u9ad8\u968e\u7af6\u6280\u5834"
        asset_dir = Path("assets/tasks/advanced_arena")
        cases = [
            ("006.png", "challenge_button.png", AdvancedArenaTask.MAIN_CHALLENGE_ROI),
            ("007.png", "free_button.png", AdvancedArenaTask.POPUP_FREE_ROI),
            ("007.png", "skip_formation_unchecked.png", AdvancedArenaTask.SKIP_FORMATION_ROI),
            ("008.png", "skip_formation_checked.png", AdvancedArenaTask.SKIP_FORMATION_ROI),
            ("009.png", "reward_item_card.png", AdvancedArenaTask.REWARD_ITEM_ROI),
            ("010.png", "reward_exit_text.png", AdvancedArenaTask.REWARD_EXIT_TEXT_ROI),
            ("011.png", "continue_button.png", AdvancedArenaTask.CONTINUE_ROI),
            ("012.png", "challenge_dialog_close_button.png", AdvancedArenaTask.POPUP_CLOSE_ROI),
        ]

        for screenshot_name, asset_name, roi in cases:
            with self.subTest(asset=asset_name):
                screen = read_image(manual_dir / screenshot_name, cv2.IMREAD_COLOR)
                match = matcher.match_template(
                    screen,
                    asset_dir / asset_name,
                    threshold=0.95,
                    roi=roi,
                )
                self.assertIsNotNone(match)


def _match(name: str, x: int, y: int) -> MatchResult:
    return MatchResult(
        template_path=Path(name),
        confidence=0.95,
        center=(x, y),
        bbox=(x - 20, y - 10, 40, 20),
    )


if __name__ == "__main__":
    unittest.main()
