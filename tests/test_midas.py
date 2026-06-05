import unittest
from types import SimpleNamespace

from src.tasks.midas import MidasTask


class FakeMatch:
    center = (123, 456)


class FakeController:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeMidasTask(MidasTask):
    def __init__(self, active_assets):
        self.active_assets = set(active_assets)
        self.context = SimpleNamespace(controller=FakeController())

    def _match_task_asset(self, asset_name, **kwargs):
        return FakeMatch() if asset_name in self.active_assets else None


class MidasSafetyTests(unittest.TestCase):
    def test_tap_if_active_does_not_tap_missing_button(self):
        task = FakeMidasTask(active_assets=())

        tapped = task._tap_if_active("free", "free_button.png", task.FREE_BUTTON_ROI)

        self.assertFalse(tapped)
        self.assertEqual(task.context.controller.taps, [])

    def test_tap_if_active_taps_active_button_once(self):
        task = FakeMidasTask(active_assets=("free_button.png",))

        tapped = task._tap_if_active("free", "free_button.png", task.FREE_BUTTON_ROI)

        self.assertTrue(tapped)
        self.assertEqual(task.context.controller.taps, [(123, 456)])


if __name__ == "__main__":
    unittest.main()
