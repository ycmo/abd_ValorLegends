from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.ui.blockers import (
    BLOCKER_POLICY_SAFE,
    REWARD_ACQUIRED_CYAN_ROI,
    REWARD_ACQUIRED_MAX_TAPS,
    BlockerHandler,
)


def _read_image(path: Path) -> np.ndarray:
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise AssertionError(f"failed to read {path}")
    return image


class FakeController:
    def __init__(self, screens=None):
        self.taps = []
        self._screens = list(screens or [])

    def tap(self, x, y):
        self.taps.append((int(x), int(y)))

    def screenshot(self):
        if not self._screens:
            return None
        if len(self._screens) > 1:
            return self._screens.pop(0)
        return self._screens[0]


def _cyan_ratio_screen(ratio: float) -> np.ndarray:
    screen = np.zeros((540, 960, 3), dtype=np.uint8)
    x, y, w, h = REWARD_ACQUIRED_CYAN_ROI
    roi = np.zeros((h, w, 3), dtype=np.uint8)
    flat = roi.reshape(-1, 3)
    cyan_pixels = int(flat.shape[0] * ratio)
    flat[:cyan_pixels] = (200, 160, 50)
    screen[y : y + h, x : x + w] = roi
    return screen


class BlockerHandlerTests(unittest.TestCase):
    def test_reward_acquired_template_pool_paths_include_reviewed_got_assets(self):
        handler = BlockerHandler(FakeController())

        names = {path.name for path in handler._reward_acquired_template_paths()}

        self.assertIn("001_got2.png", names)
        self.assertIn("018_reward_title.png", names)

    def test_reward_acquired_template_pool_matches_alpha_template(self):
        template_path = Path("assets") / "shared" / "got" / "001_got2.png"
        if not template_path.exists():
            self.skipTest("reviewed got alpha template is not available")
        template = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        th, tw = template.shape[:2]
        screen[130 : 130 + th, 410 : 410 + tw] = template[:, :, :3]
        handler = BlockerHandler(FakeController())

        match = handler.match_reward_acquired(screen)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match[0], "001_got2.png")
        self.assertGreaterEqual(match[1], 0.99)

    def test_island_signin_popup_close_x_is_handled(self):
        template_path = (
            Path("AwayFromKeyboard")
            / "integration_task"
            / "templates"
            / "blockers"
            / "island_signin_close_x.png"
        )
        if not template_path.exists():
            self.skipTest("island signin close template is not available")
        template = _read_image(template_path)
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        th, tw = template.shape[:2]
        screen[24 : 24 + th, 894 : 894 + tw] = template
        controller = FakeController()
        handler = BlockerHandler(controller)

        with patch("src.ui.blockers.time.sleep"):
            handled = handler.handle_known_blocker(screen, policy=BLOCKER_POLICY_SAFE)

        self.assertTrue(handled)
        self.assertEqual(controller.taps, [(916, 45)])

    def test_safe_policy_does_not_dismiss_reward_acquired_overlay(self):
        screen = _cyan_ratio_screen(0.35)
        controller = FakeController(screens=[screen])
        handler = BlockerHandler(controller)

        with patch("src.ui.blockers.time.sleep"):
            handled = handler.handle_known_blocker(screen, policy=BLOCKER_POLICY_SAFE)

        self.assertFalse(handled)
        self.assertEqual(controller.taps, [])

    def test_unknown_policy_is_rejected(self):
        handler = BlockerHandler(FakeController())

        with self.assertRaises(ValueError):
            handler.handle_known_blocker(np.zeros((540, 960, 3), dtype=np.uint8), policy="unknown")

    def test_reward_acquired_cyan_ignores_card_pack_banner_ratio(self):
        screen = _cyan_ratio_screen(0.27)
        handler = BlockerHandler(FakeController())

        self.assertIsNone(handler._match_reward_acquired_by_color(screen))

    def test_reward_acquired_returns_false_when_overlay_survives_all_taps(self):
        screen = _cyan_ratio_screen(0.35)
        controller = FakeController(screens=[screen])
        handler = BlockerHandler(controller)

        with patch("src.ui.blockers.time.sleep"):
            handled = handler.handle_known_blocker(screen)

        self.assertFalse(handled)
        self.assertEqual(len(controller.taps), REWARD_ACQUIRED_MAX_TAPS)

    def test_reward_acquired_overlay_from_kingdom_vault_log_is_handled(self):
        path = (
            Path("log")
            / "20260709_155000_72840_kingdom_vault"
            / "000009_20260709_155024_before_tap_687_57.png"
        )
        if not path.exists():
            self.skipTest("kingdom vault reward overlay debug screenshot is not available")
        screen = _read_image(path)
        controller = FakeController()
        handler = BlockerHandler(controller)

        with patch("src.ui.blockers.time.sleep"):
            handled = handler.handle_known_blocker(screen)

        self.assertTrue(handled)
        self.assertEqual(len(controller.taps), 1)
        self.assertLess(controller.taps[0][1], 250)
        self.assertNotEqual(controller.taps[0], (480, 500))

    def test_reward_acquired_overlay_rechecks_after_tap_before_retrying(self):
        overlay_path = (
            Path("log")
            / "20260709_165919_3360_kingdom_vault"
            / "000009_20260709_165934_before_tap_480_500.png"
        )
        normal_path = (
            Path("log")
            / "20260709_165919_3360_kingdom_vault"
            / "000011_20260709_165937_before_tap_480_500.png"
        )
        if not overlay_path.exists() or not normal_path.exists():
            self.skipTest("kingdom vault reward overlay debug screenshots are not available")
        overlay = _read_image(overlay_path)
        normal = _read_image(normal_path)
        controller = FakeController(screens=[normal])
        handler = BlockerHandler(controller)

        with patch("src.ui.blockers.time.sleep"):
            handled = handler.handle_known_blocker(overlay)

        self.assertTrue(handled)
        self.assertEqual(len(controller.taps), 1)
        self.assertLess(controller.taps[0][1], 250)

    def test_reward_acquired_overlay_from_latest_vault_swipe_log_is_detected(self):
        matches = sorted(
            Path("log").glob(
                "20260716_135415_*王國金庫_task/000021_*before_swipe_86_420_86_150_420.png"
            )
        )
        if not matches:
            self.skipTest("latest kingdom vault reward overlay before-swipe screenshot is not available")
        screen = _read_image(matches[0])
        handler = BlockerHandler(FakeController())

        match = handler.match_reward_acquired(screen)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn(match[0], {"020_006_got.png", "reward_acquired_cyan"})
        self.assertLess(match[2][1], 220)


if __name__ == "__main__":
    unittest.main()
