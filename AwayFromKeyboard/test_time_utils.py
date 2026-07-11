import unittest

from AwayFromKeyboard.time_utils import sleep_until, smart_sleep


class FakeClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        if len(self.values) == 1:
            return self.values[0]
        return self.values.pop(0)


class FakeSleeper:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class TestTimeUtils(unittest.TestCase):
    def test_smart_sleep_normal(self):
        clock = FakeClock([100.0, 100.0, 110.0, 115.0])
        sleeper = FakeSleeper()

        smart_sleep(15.0, interval_seconds=10.0, clock=clock, sleeper=sleeper)

        self.assertEqual(sleeper.calls, [10.0, 5.0])

    def test_smart_sleep_returns_after_system_sleep_time_jump(self):
        clock = FakeClock([100.0, 100.0, 600.0])
        sleeper = FakeSleeper()

        smart_sleep(15.0, interval_seconds=10.0, clock=clock, sleeper=sleeper)

        self.assertEqual(sleeper.calls, [10.0])

    def test_smart_sleep_ignores_non_positive_delay(self):
        sleeper = FakeSleeper()

        smart_sleep(-5.0, sleeper=sleeper)

        self.assertEqual(sleeper.calls, [])

    def test_sleep_until_rejects_non_positive_interval(self):
        with self.assertRaises(ValueError):
            sleep_until(100.0, interval_seconds=0)


if __name__ == "__main__":
    unittest.main()
