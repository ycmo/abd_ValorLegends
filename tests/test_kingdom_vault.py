from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.config import TASK_SPECS
from src.config import TAP_COOLDOWN_SECONDS
from src.tasks.kingdom_vault import KingdomVaultClickPlan, KingdomVaultTask
from src.vision_matcher import VisionMatcher, read_image


class FakeController:
    serial = "fake-serial"

    def __init__(self, screen):
        self._screen = screen
        self.taps = []
        self.swipes = []
        self.debug_annotations = []

    def screenshot(self):
        return self._screen.copy()

    def tap(self, x, y):
        self.taps.append((int(x), int(y)))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((int(x1), int(y1), int(x2), int(y2), int(duration_ms)))

    def annotate_next_tap_debug(self, **kwargs):
        self.debug_annotations.append(kwargs)

    def save_annotated_debug(self, *args, **kwargs):
        return None


class FakeContext:
    def __init__(self, screen):
        self.controller = FakeController(screen)
        self.matcher = VisionMatcher()
        self.logger = None
        self.finder = None
        self.navigator = None
        self.detector = None
        self.battle = None
        self.blocker = None


class FakeBlocker:
    def __init__(self, handled_count: int = 1):
        self.handled_count = handled_count
        self.calls = 0

    def handle_known_blocker(self, _screen):
        self.calls += 1
        return self.calls <= self.handled_count


class VisibleButUnclearedBlocker:
    def __init__(self):
        self.calls = 0

    def match_reward_acquired(self, _screen):
        return ("reward_acquired_cyan", 0.35, (495, 170))

    def handle_known_blocker(self, _screen):
        self.calls += 1
        return False


class KingdomVaultPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        preferred = Path("manual_screenshots") / "王國金庫"
        if preferred.exists():
            cls.base = preferred
            return
        cls.base = next(
            path
            for path in Path("manual_screenshots").iterdir()
            if path.is_dir()
            and (path / "002.png").exists()
            and (path / "003.png").exists()
            and (path / "crop_01_preview.png").exists()
            and (path / "驚嘆號.png").exists()
        )

    def test_task_spec_is_independent(self):
        self.assertEqual(TASK_SPECS["kingdom_vault"].kind, "independent")

    def test_required_assets_exist(self):
        task = KingdomVaultTask(FakeContext(read_image(self.base / "002.png", cv2.IMREAD_COLOR)))

        self.assertEqual(task.missing_assets(), ())

    def test_exclamation_badge_template_uses_alpha_mask(self):
        template = read_image(TASK_SPECS["kingdom_vault"].asset_dir / "exclamation_badge.png", cv2.IMREAD_UNCHANGED)

        self.assertEqual(template.shape[2], 4)
        self.assertGreater(cv2.countNonZero(template[:, :, 3]), 0)
        self.assertLess(cv2.countNonZero(template[:, :, 3]), template.shape[0] * template.shape[1])

    def test_event_exclamation_badge_template_uses_alpha_mask(self):
        template = read_image(
            TASK_SPECS["kingdom_vault"].asset_dir / "event_exclamation_badge.png",
            cv2.IMREAD_UNCHANGED,
        )

        self.assertEqual(template.shape[2], 4)
        self.assertGreater(cv2.countNonZero(template[:, :, 3]), 0)
        self.assertLess(cv2.countNonZero(template[:, :, 3]), template.shape[0] * template.shape[1])

    def test_title_anchor_detects_battle_pass_page(self):
        screen = read_image(self.base / "003.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        self.assertTrue(task.is_current_task_scene())

    def test_title_anchor_does_not_match_main_entry_page(self):
        screen = read_image(self.base / "001.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        self.assertFalse(task.is_task_scene(screen))

    def test_daily_free_uses_free_button_notification(self):
        screen = read_image(self.base / "002.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_daily_free_claim(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "daily_free")
        self.assertLess(abs(plan.badge_center[0] - 450), 8)
        self.assertLess(abs(plan.badge_center[1] - 216), 8)
        self.assertLess(plan.tap_point[0], plan.badge_center[0])
        self.assertGreater(plan.tap_point[1], plan.badge_center[1])

    def test_daily_free_does_not_match_paid_offer_quantity_text(self):
        path = (
            Path("log")
            / "20260709_162801_66992_kingdom_vault"
            / "000021_20260709_162835_before_tap_476_219.png"
        )
        if not path.exists():
            self.skipTest("kingdom vault paid offer debug screenshot is not available")
        screen = read_image(path, cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        self.assertIsNone(task.plan_daily_free_claim(screen))
        self.assertIsNone(task.plan_current_page_claim(screen))

    def test_special_offer_tab_uses_top_notification(self):
        screen = read_image(self.base / "006.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_special_offer_tab(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "special_offer_tab")
        self.assertLess(abs(plan.badge_center[0] - 541), 8)
        self.assertLess(abs(plan.badge_center[1] - 46), 8)
        self.assertEqual(plan.tap_point, (480, 65))

    def test_current_page_tab_is_generic_for_special_offer(self):
        screen = read_image(self.base / "006.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_current_page_tab(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "top_tab")
        self.assertLess(abs(plan.badge_center[0] - 541), 8)
        self.assertLess(abs(plan.badge_center[1] - 46), 8)
        self.assertEqual(plan.tap_point, (480, 65))

    def test_battle_pass_reset_button_is_planned_after_rewards_are_claimed(self):
        screen = read_image(self.base / "009.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_current_page_reset(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "battle_pass_reset")
        self.assertLess(abs(plan.tap_point[0] - 620), 18)
        self.assertLess(abs(plan.tap_point[1] - 492), 10)

    def test_next_action_uses_reset_when_no_higher_priority_action_exists(self):
        screen = read_image(self.base / "009.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_action(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "battle_pass_reset")

    def test_reset_confirm_dialog_is_planned(self):
        screen = read_image(self.base / "010.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_reset_confirm(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "reset_confirm")
        self.assertLess(abs(plan.tap_point[0] - 590), 18)
        self.assertLess(abs(plan.tap_point[1] - 402), 12)

    def test_reset_confirm_does_not_match_reset_page_without_dialog(self):
        screen = read_image(self.base / "009.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        self.assertIsNone(task.plan_reset_confirm(screen))

    def test_next_action_prefers_reset_confirm_dialog(self):
        screen = read_image(self.base / "010.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_action(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "reset_confirm")

    def test_weekly_special_offer_free_is_claimed_after_tab_switch(self):
        log_dir = Path("log") / "20260709_152318_46008_kingdom_vault"
        if not log_dir.exists():
            self.skipTest("latest kingdom vault debug screenshot is not available")
        screen = read_image(log_dir / "000006_20260709_152325_after_tap_479_64.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_daily_free_claim(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "daily_free")
        self.assertLess(abs(plan.badge_center[0] - 449), 8)
        self.assertLess(abs(plan.badge_center[1] - 216), 8)

    def test_battle_pass_tab_uses_top_notification(self):
        screen = read_image(self.base / "003.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_battle_pass_tab(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "battle_pass_tab")
        self.assertLess(abs(plan.badge_center[0] - 616), 8)
        self.assertLess(abs(plan.badge_center[1] - 39), 8)
        self.assertLess(plan.tap_point[0], plan.badge_center[0])
        self.assertGreater(plan.tap_point[1], plan.badge_center[1])

    def test_battle_pass_tab_scans_multiple_top_notifications(self):
        screen = read_image(self.base / "004.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))
        visited = set()

        plans = []
        for _ in range(8):
            plan = task.plan_next_battle_pass_tab(screen, visited)
            if plan is None:
                break
            plans.append(plan)
            visited.add(plan.badge_center[0] // 40)

        self.assertEqual([plan.badge_center for plan in plans], [(484, 40), (617, 40), (750, 40), (882, 40)])
        self.assertEqual([plan.tap_point for plan in plans], [(422, 58), (555, 58), (688, 58), (820, 58)])

    def test_battle_pass_reward_ignores_left_side_menu_badge(self):
        screen = read_image(self.base / "003.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_battle_pass_reward_claim(screen)

        self.assertIsNone(plan)

    def test_battle_pass_reward_claims_collect_all_badge(self):
        screen = read_image(self.base / "004.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_battle_pass_reward_claim(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "battle_pass_collect_all")
        self.assertLess(abs(plan.badge_center[0] - 600), 8)
        self.assertLess(abs(plan.badge_center[1] - 482), 8)
        self.assertLess(plan.tap_point[0], plan.badge_center[0])
        self.assertGreater(plan.tap_point[1], plan.badge_center[1])

    def test_battle_pass_collect_all_badge_can_be_on_button_right_edge(self):
        matches = sorted(
            Path("log").glob(
                "20260716_142600_*王國金庫_task/000005_*before_swipe_86_420_86_150_420.png"
            )
        )
        if not matches:
            self.skipTest("kingdom vault right-edge collect-all badge screenshot is not available")
        screen = read_image(matches[0], cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_battle_pass_reward_claim(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "battle_pass_collect_all")
        self.assertLess(abs(plan.badge_center[0] - 679), 8)
        self.assertLess(abs(plan.badge_center[1] - 482), 8)

    def test_current_page_claim_has_priority_over_top_tab_and_side_section(self):
        screen = read_image(self.base / "004.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        claim = task.plan_current_page_claim(screen)
        tab = task.plan_current_page_tab(screen)
        section = task.plan_next_side_section(screen)
        action = task.plan_next_action(screen)

        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.reason, "battle_pass_collect_all")
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.reason, "battle_pass_collect_all")
        self.assertIsNotNone(tab)
        self.assertIsNotNone(section)

    def test_ad_free_play_icon_has_priority_over_event_badge(self):
        path = Path("debug_current_adb_screen.png")
        if not path.exists():
            self.skipTest("current kingdom vault ad debug screenshot is not available")
        screen = read_image(path, cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        plan = task.plan_next_action(screen)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "ad_free")
        self.assertEqual(plan.tap_point, (736, 303))

    def test_ad_free_runs_ads2_profile_after_tap(self):
        path = Path("debug_current_adb_screen.png")
        if not path.exists():
            self.skipTest("current kingdom vault ad debug screenshot is not available")
        screen = read_image(path, cv2.IMREAD_COLOR)
        context = FakeContext(screen)
        task = KingdomVaultTask(context)
        plan = KingdomVaultClickPlan("ad_free", (700, 303), (736, 303), 1.0)

        with (
            patch("src.tasks.kingdom_vault.time.sleep"),
            patch.object(task, "_wait_for_ad_to_leave_vault") as wait_for_ad,
            patch("src.tasks.kingdom_vault.ReactiveRunner") as runner_class,
        ):
            task._tap_plan(plan)

        self.assertEqual(context.controller.taps, [(736, 303)])
        wait_for_ad.assert_called_once_with()
        runner_class.assert_called_once_with(
            serial="fake-serial",
            ad_wait=15,
            debug=False,
            profile="kingdom_vault",
        )
        runner_class.return_value.run.assert_called_once_with()

    def test_side_section_uses_left_badge_only_after_right_side_is_clear(self):
        screen = read_image(self.base / "002.png", cv2.IMREAD_COLOR)
        task = KingdomVaultTask(FakeContext(screen))

        section = task.plan_next_side_section(screen)

        self.assertIsNotNone(section)
        assert section is not None
        self.assertEqual(section.reason, "side_badge_section")
        self.assertLess(abs(section.badge_center[0] - 167), 8)
        self.assertLess(abs(section.badge_center[1] - 81), 8)
        self.assertLess(abs(section.tap_point[0] - 80), 8)
        self.assertLess(abs(section.tap_point[1] - 104), 8)

    def test_clear_loop_prefers_right_side_claim_before_side_menu_swipe(self):
        screen = read_image(self.base / "004.png", cv2.IMREAD_COLOR)
        context = FakeContext(screen)
        task = KingdomVaultTask(context)

        with patch("src.tasks.kingdom_vault.time.sleep"):
            with self.assertRaisesRegex(Exception, "exceeded"):
                task.clear_all_notifications(max_steps=1)

        self.assertEqual(context.controller.taps, [(591, 494)])
        self.assertEqual(context.controller.swipes, [])

    def test_clear_loop_searches_side_menu_with_limited_swipes_before_finishing(self):
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        context = FakeContext(screen)
        task = KingdomVaultTask(context)

        with patch("src.tasks.kingdom_vault.time.sleep"):
            message = task.clear_all_notifications(max_steps=8)

        self.assertEqual(
            context.controller.swipes,
            [
                (86, 420, 86, 150, 420),
                (86, 420, 86, 150, 420),
                (86, 420, 86, 150, 420),
                (86, 150, 86, 420, 420),
                (86, 150, 86, 420, 420),
                (86, 150, 86, 420, 420),
                (86, 150, 86, 420, 420),
            ],
        )
        self.assertEqual(context.controller.taps, [])
        self.assertEqual(message, "kingdom vault cleared; claims=0; tabs=0; sections=0; resets=0")

    def test_clear_loop_clears_known_blocker_before_side_menu_swipe(self):
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        context = FakeContext(screen)
        context.blocker = FakeBlocker(handled_count=1)
        task = KingdomVaultTask(context)

        with patch("src.tasks.kingdom_vault.time.sleep"):
            with self.assertRaisesRegex(Exception, "exceeded"):
                task.clear_all_notifications(max_steps=1)

        self.assertEqual(context.blocker.calls, 1)
        self.assertEqual(context.controller.swipes, [])

    def test_clear_loop_does_not_swipe_when_known_blocker_remains_visible(self):
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        context = FakeContext(screen)
        context.blocker = VisibleButUnclearedBlocker()
        task = KingdomVaultTask(context)

        with patch("src.tasks.kingdom_vault.time.sleep"):
            with self.assertRaisesRegex(Exception, "exceeded"):
                task.clear_all_notifications(max_steps=1)

        self.assertEqual(context.blocker.calls, 1)
        self.assertEqual(context.controller.swipes, [])

    def test_battle_pass_collect_all_is_tapped_once_per_tab(self):
        screen = read_image(self.base / "004.png", cv2.IMREAD_COLOR)
        context = FakeContext(screen)
        task = KingdomVaultTask(context)

        with patch("src.tasks.kingdom_vault.time.sleep"):
            claimed = task.claim_current_battle_pass_rewards()

        self.assertEqual(claimed, 1)
        self.assertEqual(context.controller.taps, [(591, 494)])

    def test_battle_pass_claims_current_page_before_switching_tabs(self):
        screen = read_image(self.base / "004.png", cv2.IMREAD_COLOR)
        context = FakeContext(screen)
        task = KingdomVaultTask(context)

        with patch("src.tasks.kingdom_vault.time.sleep"):
            claimed = task.claim_battle_pass_tabs(max_tabs=0)

        self.assertEqual(claimed, 1)
        self.assertEqual(context.controller.taps, [(591, 494)])

    def test_claim_taps_wait_for_reward_animation(self):
        screen = read_image(self.base / "002.png", cv2.IMREAD_COLOR)
        context = FakeContext(screen)
        task = KingdomVaultTask(context)
        sleeps = []

        with patch("src.tasks.kingdom_vault.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            task._tap_plan(KingdomVaultClickPlan("daily_free", (450, 216), (440, 228), 0.9))
            task._tap_plan(KingdomVaultClickPlan("special_offer_tab", (541, 46), (479, 64), 0.9))

        self.assertEqual(sleeps, [2.0, 0.5, TAP_COOLDOWN_SECONDS])

    def test_claim_animation_overlay_is_detected(self):
        log_dir = Path("log") / "20260709_153319_21340_kingdom_vault"
        if not log_dir.exists():
            self.skipTest("latest kingdom vault debug screenshot is not available")

        overlay = read_image(log_dir / "000011_20260709_153336_before_tap_289_57.png", cv2.IMREAD_COLOR)
        normal = read_image(log_dir / "000010_20260709_153333_after_tap_589_494.png", cv2.IMREAD_COLOR)

        self.assertTrue(KingdomVaultTask._is_claim_animation_visible(overlay))
        self.assertFalse(KingdomVaultTask._is_claim_animation_visible(normal))

    def test_wait_for_claim_animation_requires_two_clear_polls(self):
        log_dir = Path("log") / "20260709_153319_21340_kingdom_vault"
        if not log_dir.exists():
            self.skipTest("latest kingdom vault debug screenshot is not available")
        overlay = read_image(log_dir / "000011_20260709_153336_before_tap_289_57.png", cv2.IMREAD_COLOR)
        normal = read_image(log_dir / "000010_20260709_153333_after_tap_589_494.png", cv2.IMREAD_COLOR)

        class SequenceController(FakeController):
            def __init__(self, screens):
                super().__init__(screens[-1])
                self._screens = list(screens)

            def screenshot(self):
                if len(self._screens) > 1:
                    return self._screens.pop(0).copy()
                return self._screens[0].copy()

        context = FakeContext(normal)
        context.controller = SequenceController([overlay, overlay, normal, normal])
        task = KingdomVaultTask(context)
        sleeps = []

        with patch("src.tasks.kingdom_vault.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            task._wait_for_claim_animation_to_clear()

        self.assertEqual(sleeps, [0.5, 0.5, 0.5])

    def test_wait_for_claim_animation_uses_shared_blocker(self):
        screen = read_image(self.base / "002.png", cv2.IMREAD_COLOR)
        context = FakeContext(screen)
        context.blocker = FakeBlocker(handled_count=1)
        task = KingdomVaultTask(context)
        sleeps = []

        with patch("src.tasks.kingdom_vault.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            task._wait_for_claim_animation_to_clear()

        self.assertEqual(context.blocker.calls, 3)
        self.assertEqual(sleeps, [0.5])


if __name__ == "__main__":
    unittest.main()
