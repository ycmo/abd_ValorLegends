from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.blocker_handler import BlockerHandler


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


class BlockerHandlerTests(unittest.TestCase):
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

        with patch("src.blocker_handler.time.sleep"):
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

        with patch("src.blocker_handler.time.sleep"):
            handled = handler.handle_known_blocker(overlay)

        self.assertTrue(handled)
        self.assertEqual(len(controller.taps), 1)
        self.assertLess(controller.taps[0][1], 250)


if __name__ == "__main__":
    unittest.main()
