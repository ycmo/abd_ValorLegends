import unittest
from types import SimpleNamespace
from unittest.mock import patch

from magic_shop.magic_shop_task import MagicShopTask


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
                (480, 450, 480, 150, 500),
                (480, 450, 480, 150, 500),
            ],
        )


if __name__ == "__main__":
    unittest.main()
