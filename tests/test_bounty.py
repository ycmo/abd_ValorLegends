from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2

from src.config import TASK_SPECS
from src.tasks.bounty import BountyTask
from src.vision_matcher import VisionMatcher, read_image


class FakeController:
    debug_actions = False

    def __init__(self, screen):
        self._screen = screen
        self.taps = []
        self.annotations = []
        self.debug_saves = []

    def screenshot(self):
        return self._screen.copy()

    def tap(self, x, y):
        self.taps.append((int(x), int(y)))

    def annotate_next_tap_debug(self, **kwargs):
        self.annotations.append(kwargs)

    def save_annotated_debug(self, *args, **kwargs):
        self.debug_saves.append((args, kwargs))
        return None


class FakeContext(SimpleNamespace):
    def __init__(self, screen):
        super().__init__(
            controller=FakeController(screen),
            matcher=VisionMatcher(),
            navigator=None,
            logger=None,
            blocker=None,
        )


class BountyPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path("manual_screenshots") / "\u61f8\u8cde\u59d4\u8a17"

    def _task(self, image_name: str, *, use_pass_refresh: bool | None = None) -> tuple[BountyTask, object]:
        screen = read_image(self.base / image_name, cv2.IMREAD_COLOR)
        context = FakeContext(screen)
        return BountyTask(context, use_pass_refresh=use_pass_refresh), screen

    def test_required_assets_exist(self):
        task, _screen = self._task("003_\u61f8\u8cde\u59d4\u8a171.png")

        self.assertEqual(task.missing_assets(), ())

    def test_title_anchor_detects_bounty_scene(self):
        task, screen = self._task("003_\u61f8\u8cde\u59d4\u8a171.png")

        self.assertTrue(task.is_task_scene(screen))

    def test_clear_whitelist_beats_similar_blacklist(self):
        task, screen = self._task("019.png")

        with patch("src.tasks.bounty.read_current_account", return_value="default"):
            decision = task.plan_row(screen, task.ROWS[0])

        self.assertEqual(decision.action, "accept")
        self.assertEqual(decision.reason, "whitelist")
        self.assertEqual(decision.stars, 6)
        self.assertIsNotNone(decision.whitelist)
        assert decision.whitelist is not None
        self.assertEqual(decision.whitelist.template_path.name, "\u7d2b\u67311800.png")

    def test_completed_button_is_not_accepted_even_when_reward_is_whitelist(self):
        task, screen = self._task("002_\u4e00\u9375\u9818\u53d6.png")

        with patch("src.tasks.bounty.read_current_account", return_value="default"):
            decision = task.plan_row(screen, task.ROWS[1])

        self.assertEqual(decision.action, "skip")
        self.assertEqual(decision.reason, "not_accept_button")

    def test_accept_button_is_required_before_resource_decision(self):
        task, screen = self._task("003_\u61f8\u8cde\u59d4\u8a171.png")

        self.assertTrue(task._is_accept_button_available(screen, task.ROWS[0]))

    def test_blacklist_resource_is_skipped(self):
        task, screen = self._task("020.png")

        with patch("src.tasks.bounty.read_current_account", return_value="default"):
            decision = task.plan_row(screen, task.ROWS[1])

        self.assertEqual(decision.action, "skip")
        self.assertEqual(decision.reason, "blacklist")
        self.assertIsNotNone(decision.blacklist)
        assert decision.blacklist is not None
        self.assertEqual(decision.blacklist.template_path.name, "\u5149\u660e\u788e\u7247.png")

    def test_low_star_50_red_diamond_is_not_accepted_as_120_diamond(self):
        task, screen = self._task("003_\u61f8\u8cde\u59d4\u8a171.png")

        with patch("src.tasks.bounty.read_current_account", return_value="default"):
            decision = task.plan_row(screen, task.ROWS[2])

        self.assertEqual(decision.action, "skip")
        self.assertEqual(decision.reason, "below_min_stars")
        self.assertLess(decision.stars, 5)
        self.assertIsNone(decision.whitelist)

    def test_near_whitelist_low_star_is_not_accepted(self):
        task, screen = self._task("003_\u61f8\u8cde\u59d4\u8a171.png")

        with (
            patch("src.tasks.bounty.read_current_account", return_value="default"),
            patch.object(task, "_is_accept_button_available", return_value=True),
        ):
            decision = task.plan_row(screen, task.ROWS[3])

        self.assertEqual(decision.action, "skip")
        self.assertEqual(decision.reason, "below_min_stars")
        self.assertLess(decision.stars, 5)

    def test_free_refresh_detects_free_but_not_pass_refresh(self):
        free_task, free_screen = self._task("019.png")
        pass_task, pass_screen = self._task("020.png")

        self.assertIsNotNone(
            free_task.context.matcher.match_template(
                free_screen,
                free_task.asset_path("free_refresh_label.png"),
                threshold=0.84,
                roi=free_task.FREE_REFRESH_ROI,
                check_brightness=False,
            )
        )
        self.assertIsNone(
            pass_task.context.matcher.match_template(
                pass_screen,
                pass_task.asset_path("free_refresh_label.png"),
                threshold=0.84,
                roi=pass_task.FREE_REFRESH_ROI,
                check_brightness=False,
            )
        )

    def test_pass_refresh_is_not_used_by_default(self):
        task, screen = self._task("020.png", use_pass_refresh=False)

        refresh = task._tap_refresh_if_present(screen)

        self.assertIsNone(refresh)
        self.assertEqual(task.context.controller.taps, [])

    def test_pass_refresh_can_be_enabled(self):
        task, screen = self._task("020.png", use_pass_refresh=True)

        with patch("src.tasks.bounty.time.sleep"):
            refresh = task._tap_refresh_if_present(screen)

        self.assertEqual(refresh, "pass")
        self.assertEqual(task.context.controller.taps, [(850, 492)])

    def test_resource_insufficient_stops_before_pass_refresh(self):
        task, screen = self._task("006_\u59d4\u8a17\u7d50\u675f.png", use_pass_refresh=True)

        refresh = task._tap_refresh_if_present(screen)

        self.assertTrue(task._is_resource_insufficient(screen))
        self.assertIsNone(refresh)
        self.assertEqual(task.context.controller.taps, [])

    def test_execute_ends_normally_on_resource_insufficient(self):
        task, _screen = self._task("006_\u59d4\u8a17\u7d50\u675f.png", use_pass_refresh=True)

        message = task.execute()

        self.assertIn("resource_insufficient=1", message)
        self.assertEqual(task.context.controller.taps, [])

    def test_claim_all_waits_for_reward_animation(self):
        task, screen = self._task("002_\u4e00\u9375\u9818\u53d6.png")
        sleeps = []

        with patch("src.tasks.bounty.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            tapped = task._tap_claim_all_if_present(screen)

        self.assertTrue(tapped)
        self.assertEqual(sleeps, [2.0])

    def test_claim_all_alt_template_detects_stable_text_state(self):
        task, screen = self._task("002_\u4e00\u9375\u9818\u53d6.png")

        claim = task._best_claim_all_match(screen)

        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.template_path.name, "claim_all_button_alt.png")
        self.assertGreaterEqual(claim.confidence, 0.99)

    def test_accept_all_button_does_not_trigger_claim_all(self):
        task, screen = self._task("003_\u61f8\u8cde\u59d4\u8a171.png")

        with patch("src.tasks.bounty.time.sleep"):
            tapped = task._tap_claim_all_if_present(screen)

        self.assertFalse(tapped)
        self.assertEqual(task.context.controller.taps, [])


if __name__ == "__main__":
    unittest.main()
