import unittest

from src.exceptions import TaskFailedError
from src.tasks.time_travel import TimeTravelTask


class FakeTimeTravelTask(TimeTravelTask):
    def __init__(self, hundred_visible=False):
        self.hundred_visible = hundred_visible
        self.tapped = []

    def _match_task_asset(self, asset_name, **kwargs):
        if asset_name == "gem_100_button.png" and self.hundred_visible:
            return object()
        return None

    def _tap_task_asset(self, label, asset_name, **kwargs):
        self.tapped.append((label, asset_name))
        return object()


class TimeTravelSafetyTests(unittest.TestCase):
    def test_stops_before_100_gem_tier(self):
        task = FakeTimeTravelTask(hundred_visible=True)

        with self.assertRaises(TaskFailedError):
            task._tap_gem_50()

        self.assertEqual(task.tapped, [])

    def test_taps_50_when_100_tier_is_not_visible(self):
        task = FakeTimeTravelTask(hundred_visible=False)

        task._tap_gem_50()

        self.assertEqual(task.tapped, [("50-gem time travel", "gem_50_button.png")])


if __name__ == "__main__":
    unittest.main()
