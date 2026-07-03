import unittest
import cv2
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from magic_shop.magic_shop_task import MagicShopTask
from src.vision_matcher import VisionMatcher, read_image


class FakeMatch:
    def __init__(self, confidence=0.95, center=(850, 55)):
        self.confidence = confidence
        self.center = center


class RefreshProbeTask(MagicShopTask):
    def __init__(self, conf_100, conf_200):
        self.context = SimpleNamespace()
        self.conf_by_asset = {
            "刷新100.png": conf_100,
            "刷新200.png": conf_200,
        }

    def _refresh_template_probe(self, screen, asset_name):
        confidence = self.conf_by_asset.get(asset_name, 0.0)
        if asset_name == "刷新100.png":
            return FakeMatch(confidence)
        if asset_name == "刷新200.png":
            return FakeMatch(confidence)
        return None


class FakeController:
    def __init__(self):
        self.swipes = []

    def swipe(self, x1, y1, x2, y2, *, duration_ms):
        self.swipes.append((x1, y1, x2, y2, duration_ms))


class ScanTask(MagicShopTask):
    def __init__(self, bought_per_view):
        self.context = SimpleNamespace(controller=FakeController())
        self.bought_per_view = iter(bought_per_view)
        self.scan_calls = 0

    def buy_items_on_screen(self, dry_run=False, ignore_boxes=None):
        self.scan_calls += 1
        return next(self.bought_per_view)


class MagicShopScanTests(unittest.TestCase):
    def test_scans_three_overlapping_views_with_two_controlled_swipes(self):
        task = ScanTask([1, 2, 3])

        with patch("magic_shop.magic_shop_task.time.sleep"):
            bought = task._scan_shop_views()

        self.assertEqual(bought, 6)
        self.assertEqual(task.scan_calls, 3)
        self.assertEqual(
            task.context.controller.swipes,
            [
                (480, 450, 480, 150, 900),
                (480, 450, 480, 150, 900),
            ],
        )

    def test_template_candidates_require_matching_item_icon_and_price(self):
        screenshot = Path("manual_screenshots/魔法商店/001_要購買2.png")
        if not screenshot.exists():
            self.skipTest(f"missing manual screenshot: {screenshot}")

        task = MagicShopTask.__new__(MagicShopTask)
        task.context = SimpleNamespace(matcher=VisionMatcher())
        screen = read_image(screenshot, cv2.IMREAD_COLOR)

        candidates = task._find_buyable_item_candidates(screen)
        found = {(text, template) for text, template, _match in candidates}

        self.assertIn(("480k", "競技場券480k.png"), found)
        self.assertIn(("1800k", "英雄碎片1800k.png"), found)
        self.assertNotIn(("5000k", "金牌5000k.png"), found)

    def test_480k_price_only_fallback_handles_edge_clipped_icon(self):
        screenshot = Path(
            "log/20260627_094341_11636_run_all/"
            "000156_20260627_095212_before_tap_500_387.png"
        )
        if not screenshot.exists():
            self.skipTest(f"missing action debug screenshot: {screenshot}")

        task = MagicShopTask.__new__(MagicShopTask)
        task.context = SimpleNamespace(matcher=VisionMatcher())
        screen = read_image(screenshot, cv2.IMREAD_COLOR)

        candidates = task._find_buyable_item_candidates(screen)
        found = {(text, template) for text, template, _match in candidates}

        self.assertIn(("480k", "競技場券480k.png"), found)

    def test_refresh_100_must_win_against_200_by_margin(self):
        task = RefreshProbeTask(0.96, 0.70)

        match = task._find_safe_refresh_100(object())

        self.assertIsNotNone(match)
        self.assertEqual(match.center, (850, 55))

    def test_refresh_200_close_match_blocks_refresh(self):
        task = RefreshProbeTask(0.90, 0.88)

        self.assertIsNone(task._find_safe_refresh_100(object()))

    def test_refresh_100_below_threshold_blocks_refresh(self):
        task = RefreshProbeTask(0.81, 0.20)

        self.assertIsNone(task._find_safe_refresh_100(object()))


if __name__ == "__main__":
    unittest.main()
