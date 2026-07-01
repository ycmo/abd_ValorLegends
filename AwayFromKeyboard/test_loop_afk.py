import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from AwayFromKeyboard import task_config
from AwayFromKeyboard import loop_afk


class LoopAfkCompletionTests(unittest.TestCase):
    def test_today_key_uses_taipei_reset_day(self):
        utc_time = datetime(2026, 6, 25, 17, 30, tzinfo=timezone.utc)

        self.assertEqual(loop_afk.today_key(utc_time), "2026-06-25")

    def test_today_key_switches_at_taipei_8am(self):
        before_reset = datetime(2026, 6, 27, 7, 59, tzinfo=loop_afk.TAIPEI_TZ)
        at_reset = datetime(2026, 6, 27, 8, 0, tzinfo=loop_afk.TAIPEI_TZ)

        self.assertEqual(loop_afk.today_key(before_reset), "2026-06-26")
        self.assertEqual(loop_afk.today_key(at_reset), "2026-06-27")

    def test_delay_until_8_can_add_extra_delay(self):
        now = datetime(2026, 6, 27, 6, 30, 0)

        delay_seconds, wake_time, label = loop_afk.resolve_start_delay(
            delay="00:10:00",
            delay_until_8=True,
            now=now,
        )

        self.assertEqual(delay_seconds, 100 * 60)
        self.assertEqual(wake_time, datetime(2026, 6, 27, 8, 10, 0))
        self.assertIn("08:00:00", label)
        self.assertIn("00:10:00", label)

    def test_delay_without_until_8_keeps_original_behavior(self):
        now = datetime(2026, 6, 27, 6, 30, 0)

        delay_seconds, wake_time, _ = loop_afk.resolve_start_delay(
            delay="00:10:00",
            delay_until_8=False,
            now=now,
        )

        self.assertEqual(delay_seconds, 10 * 60)
        self.assertEqual(wake_time, datetime(2026, 6, 27, 6, 40, 0))

    def test_ini_start_time_delays_until_today_when_future(self):
        now = datetime(2026, 6, 27, 7, 0, 0)

        delay_seconds, wake_time, label = loop_afk.resolve_start_delay(
            delay=None,
            delay_until_8=False,
            config_start_time="08:10:00",
            now=now,
        )

        self.assertEqual(delay_seconds, 70 * 60)
        self.assertEqual(wake_time, datetime(2026, 6, 27, 8, 10, 0))
        self.assertIn("start_time", label)

    def test_ini_start_time_delays_until_tomorrow_when_past(self):
        now = datetime(2026, 6, 27, 9, 0, 0)

        delay_seconds, wake_time, _ = loop_afk.resolve_start_delay(
            delay=None,
            delay_until_8=False,
            config_start_time="08:10:00",
            now=now,
        )

        self.assertEqual(delay_seconds, 23 * 3600 + 10 * 60)
        self.assertEqual(wake_time, datetime(2026, 6, 28, 8, 10, 0))

    def test_cli_delay_overrides_ini_start_time(self):
        now = datetime(2026, 6, 27, 6, 30, 0)

        delay_seconds, wake_time, _ = loop_afk.resolve_start_delay(
            delay="00:10:00",
            delay_until_8=False,
            config_start_time="08:10:00",
            now=now,
        )

        self.assertEqual(delay_seconds, 10 * 60)
        self.assertEqual(wake_time, datetime(2026, 6, 27, 6, 40, 0))

    def test_run_now_overrides_ini_start_time(self):
        now = datetime(2026, 6, 27, 6, 30, 0)

        delay_seconds, wake_time, label = loop_afk.resolve_start_delay(
            delay=None,
            delay_until_8=False,
            config_start_time="08:10:00",
            run_now=True,
            now=now,
        )

        self.assertEqual(delay_seconds, 0)
        self.assertEqual(wake_time, now)
        self.assertEqual(label, "立刻執行")

    def test_pending_tasks_skips_completed_routes_unless_forced(self):
        state = {
            "date": "2026-06-26",
            "completed": {
                "em3": {
                    "每日任務": "2026-06-26T08:00:00+08:00",
                }
            },
        }
        tasks = ["每日任務", "深淵"]

        self.assertEqual(
            loop_afk.pending_tasks_for_account(state, "em3", tasks, force=False),
            ["深淵"],
        )
        self.assertEqual(
            loop_afk.pending_tasks_for_account(state, "em3", tasks, force=True),
            tasks,
        )

    def test_account_rotation_starts_from_current_account(self):
        accounts = ["em3", "311", "tiger", "14"]

        self.assertEqual(
            loop_afk.build_account_rotation(accounts, "tiger"),
            ["tiger", "14", "em3", "311"],
        )
        self.assertEqual(
            loop_afk.build_account_rotation(accounts, None),
            accounts,
        )

    def test_account_execution_order_prefers_current_account_type(self):
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }

        self.assertEqual(
            loop_afk.build_account_execution_order(
                accounts,
                "14",
                {"date": "2026-06-26", "completed": {}},
                ["每日任務"],
                force=False,
            ),
            ["14", "tiger", "em3", "311"],
        )

    def test_account_execution_order_removes_completed_accounts(self):
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }
        state = {
            "date": "2026-06-26",
            "completed": {
                "14": {"每日任務": "2026-06-26T08:00:00+08:00"},
                "em3": {"每日任務": "2026-06-26T08:00:00+08:00"},
            },
        }

        self.assertEqual(
            loop_afk.build_account_execution_order(
                accounts,
                "14",
                state,
                ["每日任務"],
                force=False,
            ),
            ["tiger", "311"],
        )

    def test_account_execution_order_force_keeps_completed_accounts(self):
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }
        state = {
            "date": "2026-06-26",
            "completed": {
                "14": {"每日任務": "2026-06-26T08:00:00+08:00"},
                "em3": {"每日任務": "2026-06-26T08:00:00+08:00"},
            },
        }

        self.assertEqual(
            loop_afk.build_account_execution_order(
                accounts,
                "14",
                state,
                ["每日任務"],
                force=True,
            ),
            ["14", "tiger", "em3", "311"],
        )

    def test_mark_route_completed_writes_daily_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(loop_afk, "STATE_DIR", Path(tmpdir)):
                state = {"date": "2026-06-26", "completed": {}}

                loop_afk.mark_route_completed(state, "em3", "每日任務")
                loaded = loop_afk.load_completion_state("2026-06-26")

        self.assertTrue(loop_afk.is_route_completed(loaded, "em3", "每日任務"))

    def test_runtime_task_state_reloads_enabled_tasks_each_call(self):
        task_lists = [["每日任務"], ["深淵", "疾風呼喚"]]

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(loop_afk, "STATE_DIR", Path(tmpdir)), \
             patch.object(loop_afk, "today_key", return_value="2026-06-26"), \
             patch("AwayFromKeyboard.task_config.get_tasks_to_run", side_effect=task_lists):
            first_tasks, _, _ = loop_afk.load_runtime_task_state()
            second_tasks, _, _ = loop_afk.load_runtime_task_state()

        self.assertEqual(first_tasks, ["每日任務"])
        self.assertEqual(second_tasks, ["深淵", "疾風呼喚"])

    def test_route_log_file_uses_project_relative_directory(self):
        path = loop_afk.build_route_log_file(
            "debug",
            account_name="em3",
            task_name="每日任務",
            now=datetime(2026, 7, 1, 9, 1, 2, tzinfo=loop_afk.TAIPEI_TZ),
        )

        self.assertEqual(
            path,
            loop_afk.PROJECT_ROOT / "debug" / "afk_20260701_090102_em3_每日任務.txt",
        )

    def test_route_log_file_sanitizes_unsafe_name_parts(self):
        path = loop_afk.build_route_log_file(
            "debug",
            account_name="em:3",
            task_name="深淵/測試",
            now=datetime(2026, 7, 1, 9, 1, 2, tzinfo=loop_afk.TAIPEI_TZ),
        )

        self.assertEqual(path.name, "afk_20260701_090102_em_3_深淵_測試.txt")

    def test_task_config_can_use_env_ini_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom.ini"
            config_path.write_text(
                "[settings]\n"
                "start_time = 08:10:00\n\n"
                "[每日任務]\n"
                "enable = N\n"
                "command = -m src.main run-all\n\n"
                "[深淵]\n"
                "enable = Y\n"
                "command = -m src.main run-current-scene-task abyss\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"AFK_TASKS_INI": str(config_path)}):
                self.assertEqual(task_config.get_config_file(), config_path.resolve())
                self.assertEqual(task_config.get_tasks_to_run(), ["深淵"])
                self.assertEqual(task_config.get_start_time(), "08:10:00")


if __name__ == "__main__":
    unittest.main()
