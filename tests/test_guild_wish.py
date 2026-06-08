from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from types import SimpleNamespace

import cv2

from src.tasks.guild_wish import GuildWishTask
from src.vision_matcher import VisionMatcher, read_image


GUILD_WISH_DIR = Path("manual_screenshots") / "\u516c\u6703\u7948\u9858"


class FakeController:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeGuildWishOverlayTask(GuildWishTask):
    def __init__(self):
        self.context = SimpleNamespace(controller=FakeController())
        self.closed = False
        self.visible_checks = [False, True]

    def _is_guild_wish_dialog_ready(self, timeout_seconds=1.0):
        return False

    def _is_guild_wish_dialog_visible(self, timeout_seconds=0.8):
        if self.visible_checks:
            return self.visible_checks.pop(0)
        return True

    def _close_dialog(self):
        self.closed = True


class GuildWishTemplateTests(TestCase):
    def test_guild_wish_templates_match_manual_dialog(self):
        matcher = VisionMatcher()
        screen = read_image(GUILD_WISH_DIR / "002_\u516c\u6703\u7948\u9858.png", cv2.IMREAD_COLOR)
        cases = [
            ("guild_wish_title.png", GuildWishTask.TITLE_ROI),
            ("ordinary_wish_label.png", GuildWishTask.ORDINARY_LABEL_ROI),
            ("free_wish_button.png", GuildWishTask.FREE_BUTTON_ROI),
            ("close_button.png", GuildWishTask.CLOSE_BUTTON_ROI),
        ]

        for asset_name, roi in cases:
            with self.subTest(asset=asset_name):
                match = matcher.match_template(
                    screen,
                    Path("assets/tasks/guild_wish") / asset_name,
                    threshold=0.95,
                    roi=roi,
                )
                self.assertIsNotNone(match)

    def test_current_reward_overlay_uses_blank_tap_then_closes(self):
        task = FakeGuildWishOverlayTask()

        message = task.execute_from_current_scene()

        self.assertEqual(message, "free guild wish completed after reward overlay")
        self.assertEqual(task.context.controller.taps, [(80, 500)])
        self.assertTrue(task.closed)
