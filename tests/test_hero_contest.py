from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2

from src.exceptions import TaskFailedError
from src.tasks.hero_contest import HeroContestResult, HeroContestTask
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
        return None


class FakeMatcher:
    def __init__(self, *, sequences=None, matches=None, best_matches=None):
        self.sequences = {name: list(values) for name, values in (sequences or {}).items()}
        self.matches = matches or {}
        self.best_matches = best_matches or {}

    def match_template(self, _screen, path, **_kwargs):
        values = self.sequences.get(path.name)
        if values:
            return values.pop(0)
        return self.matches.get(path.name)

    def best_template_match(self, _screen, path, **_kwargs):
        return self.best_matches.get(path.name)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, message, *, force=False):
        self.messages.append(message)


class HeroContestTests(unittest.TestCase):
    def test_execute_runs_four_fights_without_refresh_when_winning(self):
        controller = FakeController()
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "challenge_button.png": _match("challenge_button.png", 580, 465),
                        "hero_tab_anchor.png": _match("hero_tab_anchor.png", 68, 114),
                        "battle_challenge_button.png": _match("battle_challenge_button.png", 910, 504),
                        "skip_button.png": _match("skip_button.png", 916, 104),
                        "victory_continue_button.png": _match("victory_continue_button.png", 480, 485),
                    }
                ),
                logger=FakeLogger(),
            )
        )

        with patch("src.tasks.hero_contest.time.sleep"):
            message = task.execute()

        self.assertIn("fights=4", message)
        self.assertIn("wins=4", message)
        self.assertIn("refreshes=0", message)
        self.assertEqual(len(controller.taps), 16)

    def test_execute_continues_after_loss_until_four_wins(self):
        controller = FakeController()
        loss = _match("defeat_continue_button.png", 480, 508)
        win = _match("victory_continue_button.png", 480, 485)
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    sequences={
                        "victory_continue_button.png": [win, win, None, win, win],
                        "defeat_continue_button.png": [loss],
                    },
                    matches={
                        "challenge_button.png": _match("challenge_button.png", 580, 465),
                        "hero_tab_anchor.png": _match("hero_tab_anchor.png", 68, 114),
                        "battle_challenge_button.png": _match("battle_challenge_button.png", 910, 504),
                        "skip_button.png": _match("skip_button.png", 916, 104),
                    },
                ),
                logger=FakeLogger(),
            )
        )

        with patch("src.tasks.hero_contest.time.sleep"):
            message = task.execute()

        self.assertIn("fights=5", message)
        self.assertIn("wins=4", message)
        self.assertIn("losses=1", message)

    def test_execute_refreshes_after_two_consecutive_losses(self):
        controller = FakeController()
        loss = _match("defeat_continue_button.png", 480, 508)
        win = _match("victory_continue_button.png", 480, 485)
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    sequences={
                        "victory_continue_button.png": [None, None, win, win],
                        "defeat_continue_button.png": [loss, loss],
                    },
                    matches={
                        "challenge_button.png": _match("challenge_button.png", 580, 465),
                        "hero_tab_anchor.png": _match("hero_tab_anchor.png", 68, 114),
                        "battle_challenge_button.png": _match("battle_challenge_button.png", 910, 504),
                        "skip_button.png": _match("skip_button.png", 916, 104),
                        "refresh_button.png": _match("refresh_button.png", 580, 380),
                        "hero_tab_anchor.png": _match("hero_tab_anchor.png", 68, 114),
                    },
                ),
                logger=FakeLogger(),
            )
        )
        task.TARGET_REWARD_WINS = 2

        with patch("src.tasks.hero_contest.time.sleep"):
            message = task.execute()

        self.assertIn("losses=2", message)
        self.assertIn("refreshes=1", message)
        self.assertIn((580, 380), controller.taps)

    def test_main_screen_can_be_detected_from_refresh_button(self):
        task = HeroContestTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "refresh_button.png": _match("refresh_button.png", 580, 380),
                    }
                ),
            )
        )

        self.assertTrue(task.is_task_scene("screen"))

    def test_main_screen_detection_accepts_challenge_and_refresh_without_tab(self):
        task = HeroContestTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "challenge_button.png": _match("challenge_button.png", 580, 465),
                        "refresh_button.png": _match("refresh_button.png", 580, 380),
                    }
                ),
            )
        )

        self.assertIsNotNone(task._find_main_screen_on_screen("screen"))

    def test_execute_stops_when_attempts_are_zero(self):
        controller = FakeController()
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    best_matches={
                        "attempts_zero_anchor.png": _match("attempts_zero_anchor.png", 636, 501),
                    }
                ),
                logger=FakeLogger(),
            )
        )

        message = task.execute()

        self.assertIn("fights=0", message)
        self.assertEqual(controller.taps, [])
        self.assertEqual(controller.debug_saves[0][0][0], "hero_contest_attempts_zero_probe")

    def test_result_continue_retries_only_with_fresh_result_match(self):
        controller = FakeController()
        result = _match("victory_continue_button.png", 480, 484)
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "victory_continue_button.png": result,
                    }
                ),
                logger=FakeLogger(),
            )
        )

        with patch("src.tasks.hero_contest.time.sleep"), \
             patch("src.tasks.hero_contest.time.time", side_effect=[0, 1, 2, 3]):
            with self.assertRaises(TaskFailedError):
                task._dismiss_result(HeroContestResult("win", result))

        self.assertEqual(controller.taps, [(480, 484), (480, 484), (480, 484)])
        self.assertEqual(controller.debug_saves[0][0][0], "hero_contest_result_continue_still_visible")

    def test_result_continue_does_not_retry_on_unknown_screen(self):
        controller = FakeController()
        result = _match("victory_continue_button.png", 480, 484)
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(),
                logger=FakeLogger(),
            )
        )

        with patch("src.tasks.hero_contest.time.sleep"), \
             patch("src.tasks.hero_contest.time.time", side_effect=[0, 1, 16]):
            task._dismiss_result(HeroContestResult("win", result))

        self.assertEqual(controller.taps, [(480, 484)])

    def test_recover_to_main_uses_hero_contest_route_step_when_not_visible(self):
        controller = FakeController()
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(),
                logger=FakeLogger(),
            )
        )
        calls = []

        with patch.object(task, "_is_main_screen_visible", side_effect=[False, True]), \
             patch.object(task, "_execute_afk_route_step", side_effect=lambda prefix: calls.append(prefix)):
            self.assertTrue(task._recover_to_main_screen_after_result())

        self.assertEqual(calls, ["02"])

    def test_recover_to_main_saves_probe_debug_when_route_step_still_not_visible(self):
        controller = FakeController()
        task = HeroContestTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(),
                logger=FakeLogger(),
            )
        )

        with patch.object(task, "_execute_afk_route_step"), \
             patch("src.tasks.hero_contest.time.sleep"), \
             patch("src.tasks.hero_contest.time.time", side_effect=[0, 1, 2, 10, 10.1, 19]):
            self.assertFalse(task._recover_to_main_screen_after_result())

        labels = [args[0] for args, _kwargs in controller.debug_saves]
        self.assertIn("hero_contest_main_screen_probe", labels)

    def test_templates_match_manual_screenshots(self):
        matcher = VisionMatcher()
        manual_dir = Path("manual_screenshots") / "\u52c7\u8005\u89d2\u9010"
        asset_dir = Path("assets/tasks/hero_contest")
        cases = [
            ("001.png", "challenge_button.png", HeroContestTask.MAIN_CHALLENGE_ROI),
            ("001.png", "hero_tab_anchor.png", HeroContestTask.HERO_TAB_ROI),
            ("001.png", "refresh_button.png", HeroContestTask.REFRESH_ROI),
            ("002.png", "battle_challenge_button.png", HeroContestTask.TEAM_CHALLENGE_ROI),
            ("003.png", "skip_button.png", HeroContestTask.SKIP_ROI),
            ("004_\u52dd\u5229.png", "victory_continue_button.png", HeroContestTask.VICTORY_CONTINUE_ROI),
            ("004_\u5931\u6557.png", "defeat_continue_button.png", HeroContestTask.DEFEAT_CONTINUE_ROI),
            ("005_\u7d50\u675f.png", "attempts_zero_anchor.png", HeroContestTask.ATTEMPTS_ZERO_ROI),
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
