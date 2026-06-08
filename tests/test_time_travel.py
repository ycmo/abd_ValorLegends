import unittest

from src.exceptions import TaskFailedError
from src.tasks.time_travel import TimeTravelTask


class FakeTimeTravelTask(TimeTravelTask):
    def __init__(self, costs, dialog_visible=True, free_visible=False):
        self.costs = list(costs)
        self.dialog_visible = dialog_visible
        self.free_visible = free_visible
        self.tapped = []
        self.dismiss_count = 0
        self.require_count = 0
        self.close_count = 0

    def _detect_action_cost(self, screen=None):
        if not self.costs:
            return None
        return self.costs.pop(0)

    def _is_time_travel_dialog_screen(self, _screen):
        return self.dialog_visible

    def _tap_task_asset(self, label, asset_name, **kwargs):
        self.tapped.append((label, asset_name))
        return object()

    def _dismiss_reward_overlay_if_present(self):
        self.dismiss_count += 1

    def _require_time_travel_dialog(self):
        self.require_count += 1
        return object()

    def _tap_free_if_visible(self):
        if not self.free_visible:
            return False
        self.free_visible = False
        self.tapped.append(("free time travel", "free_button.png"))
        return True

    def _close_dialog_if_visible(self):
        self.close_count += 1

    @property
    def context(self):
        class Controller:
            def screenshot(self):
                return object()

        return type("Context", (), {"controller": Controller()})()


class TimeTravelSafetyTests(unittest.TestCase):
    def test_stops_before_100_gem_tier(self):
        task = FakeTimeTravelTask([100])

        with self.assertRaises(TaskFailedError):
            task._tap_gem_50()

        self.assertEqual(task.tapped, [])

    def test_taps_50_when_100_tier_is_not_visible(self):
        task = FakeTimeTravelTask([50])

        task._tap_gem_50()

        self.assertEqual(task.tapped, [("50-gem time travel", "gem_50_button.png")])

    def test_taps_all_50_gem_tiers_until_100(self):
        task = FakeTimeTravelTask([50, 50, 100])

        count = task._tap_all_gem_50()

        self.assertEqual(count, 2)
        self.assertEqual(
            task.tapped,
            [
                ("50-gem time travel", "gem_50_button.png"),
                ("50-gem time travel", "gem_50_button.png"),
            ],
        )
        self.assertEqual(task.dismiss_count, 2)

    def test_unknown_cost_stops_before_tapping(self):
        task = FakeTimeTravelTask([None])

        with self.assertRaises(TaskFailedError):
            task._tap_all_gem_50()

        self.assertEqual(task.tapped, [])

    def test_dialog_closed_after_50_counts_as_finished(self):
        task = FakeTimeTravelTask([50])
        visible = [True, False]
        task._is_time_travel_dialog_screen = lambda _screen: visible.pop(0)

        count = task._tap_all_gem_50()

        self.assertEqual(count, 1)
        self.assertEqual(task.tapped, [("50-gem time travel", "gem_50_button.png")])

    def test_execute_continues_from_50_tier_without_tapping_free(self):
        task = FakeTimeTravelTask([50, 100], free_visible=False)

        message = task.execute_from_current_scene()

        self.assertEqual(message, "time travel completed: 1x 50-gem")
        self.assertEqual(task.tapped, [("50-gem time travel", "gem_50_button.png")])
        self.assertEqual(task.close_count, 1)

    def test_execute_taps_free_when_available_then_all_50_tiers(self):
        task = FakeTimeTravelTask([50, 50, 100], free_visible=True)

        message = task.execute_from_current_scene()

        self.assertEqual(message, "time travel completed: free, 2x 50-gem")
        self.assertEqual(
            task.tapped,
            [
                ("free time travel", "free_button.png"),
                ("50-gem time travel", "gem_50_button.png"),
                ("50-gem time travel", "gem_50_button.png"),
            ],
        )
        self.assertEqual(task.close_count, 1)


if __name__ == "__main__":
    unittest.main()
