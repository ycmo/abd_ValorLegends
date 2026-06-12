import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from src.daily_runner import DailyRunner
from src.task_runner import TaskRunResult, TaskState


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, message, force=False):
        self.messages.append((message, force))


class FakeContext:
    def __init__(self):
        self.logger = FakeLogger()


class DailyRunnerRunAllTests(unittest.TestCase):
    def test_run_all_logs_sleeps_and_continues_after_adb_stall_result(self):
        runner = DailyRunner(context=FakeContext())
        calls = []

        def fake_run_task(task_key):
            calls.append(task_key)
            if task_key == "summon":
                return TaskRunResult(task_key, TaskState.FAILED, "ADB screenshot timed out", 1.2)
            return TaskRunResult(task_key, TaskState.COMPLETED, "ok", 0.5)

        runner.run_task = fake_run_task

        out = io.StringIO()
        with patch("src.daily_runner.time.sleep") as sleep, redirect_stdout(out):
            results = runner.run_all(["summon", "midas"], failure_sleep_seconds=0.1)

        self.assertEqual(calls, ["summon", "midas"])
        self.assertEqual([result.state for result in results], [TaskState.FAILED, TaskState.COMPLETED])
        sleep.assert_called_once_with(0.1)
        self.assertIn("task=summon failed: ADB screenshot timed out", out.getvalue())
        self.assertIn("ADB may be stalled", out.getvalue())

    def test_run_all_logs_and_continues_without_sleep_after_normal_failed_result(self):
        runner = DailyRunner(context=FakeContext())

        def fake_run_task(task_key):
            if task_key == "arena":
                return TaskRunResult(
                    task_key,
                    TaskState.FAILED,
                    "Cannot find runnable task row for 競技場",
                    1.2,
                )
            return TaskRunResult(task_key, TaskState.COMPLETED, "ok", 0.5)

        runner.run_task = fake_run_task

        out = io.StringIO()
        with patch("src.daily_runner.time.sleep") as sleep, redirect_stdout(out):
            results = runner.run_all(["arena", "midas"], failure_sleep_seconds=0.1)

        self.assertEqual([result.state for result in results], [TaskState.FAILED, TaskState.COMPLETED])
        sleep.assert_not_called()
        self.assertIn("task=arena failed: Cannot find runnable task row for 競技場", out.getvalue())
        self.assertNotIn("sleeping", out.getvalue())

    def test_run_all_converts_unhandled_exception_to_failed_result(self):
        runner = DailyRunner(context=FakeContext())

        def fake_run_task(task_key):
            if task_key == "summon":
                raise RuntimeError("emulator stalled")
            return TaskRunResult(task_key, TaskState.COMPLETED, "ok", 0.5)

        runner.run_task = fake_run_task

        with patch("src.daily_runner.time.sleep") as sleep:
            results = runner.run_all(["summon", "midas"], failure_sleep_seconds=0)

        self.assertEqual(results[0].task_key, "summon")
        self.assertEqual(results[0].state, TaskState.FAILED)
        self.assertEqual(results[0].message, "RuntimeError: emulator stalled")
        self.assertEqual(results[1].state, TaskState.COMPLETED)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
