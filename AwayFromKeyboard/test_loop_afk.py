import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_delay_until_8_waits_until_8_00_30_and_can_add_extra_delay(self):
        now = datetime(2026, 6, 27, 6, 30, 0)

        delay_seconds, wake_time, label = loop_afk.resolve_start_delay(
            delay="00:10:00",
            delay_until_8=True,
            now=now,
        )

        self.assertEqual(delay_seconds, 100 * 60 + 30)
        self.assertEqual(wake_time, datetime(2026, 6, 27, 8, 10, 30))
        self.assertIn("08:00:30", label)
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

    def test_parse_duration_accepts_seconds_and_hh_mm_ss(self):
        self.assertEqual(loop_afk.parse_duration_to_seconds("90"), 90)
        self.assertEqual(loop_afk.parse_duration_to_seconds("00:02:30"), 150)
        self.assertIsNone(loop_afk.parse_duration_to_seconds(""))

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

    def test_failed_this_round_is_written_and_cleared_without_completing_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(loop_afk, "STATE_DIR", Path(tmpdir)):
                state = {"date": "2026-06-26", "completed": {}}

                loop_afk.mark_route_failed_this_round(state, "em3", "route_a", "returncode=1")
                loaded = loop_afk.load_completion_state("2026-06-26")

                self.assertTrue(loop_afk.is_route_failed_this_round(loaded, "em3", "route_a"))
                self.assertFalse(loop_afk.is_route_completed(loaded, "em3", "route_a"))
                self.assertEqual(
                    loop_afk.pending_tasks_for_account(loaded, "em3", ["route_a", "route_b"], force=False),
                    ["route_b"],
                )
                self.assertEqual(
                    loop_afk.pending_tasks_for_account(loaded, "em3", ["route_a", "route_b"], force=True),
                    ["route_a", "route_b"],
                )

                self.assertTrue(loop_afk.clear_failed_this_round(loaded))
                reloaded = loop_afk.load_completion_state("2026-06-26")

        self.assertFalse(loop_afk.is_route_failed_this_round(reloaded, "em3", "route_a"))
        self.assertEqual(
            loop_afk.pending_tasks_for_account(reloaded, "em3", ["route_a", "route_b"], force=False),
            ["route_a", "route_b"],
        )

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
            True,
            account_name="em3",
            task_name="每日任務",
            now=datetime(2026, 7, 1, 9, 1, 2, tzinfo=loop_afk.TAIPEI_TZ),
        )

        self.assertEqual(
            path,
            loop_afk.PROJECT_ROOT / "log" / "afk_20260701_090102_em3_每日任務.txt",
        )

    def test_route_log_file_sanitizes_unsafe_name_parts(self):
        path = loop_afk.build_route_log_file(
            True,
            account_name="em:3",
            task_name="深淵/測試",
            now=datetime(2026, 7, 1, 9, 1, 2, tzinfo=loop_afk.TAIPEI_TZ),
        )

        self.assertEqual(path.name, "afk_20260701_090102_em_3_深淵_測試.txt")

    def test_route_log_file_disabled_returns_none(self):
        self.assertIsNone(
            loop_afk.build_route_log_file(
                False,
                account_name="em3",
                task_name="每日任務",
            )
        )

    def test_build_router_argv_includes_debug_force_and_log(self):
        argv = loop_afk.build_router_argv(
            "深淵",
            debug_actions=True,
            force_subprocess=True,
            route_log_file=Path("log") / "route.txt",
        )

        self.assertEqual(
            argv,
            ["深淵", "--debug-actions", "--force-subprocess", "--log-file", str(Path("log") / "route.txt")],
        )

    def test_run_router_task_defaults_to_in_process(self):
        with patch.object(loop_afk, "run_router_task_in_process", return_value=0) as in_process, \
             patch("AwayFromKeyboard.loop_afk.subprocess.run") as subprocess_run:
            returncode = loop_afk.run_router_task(
                task_cmd=["python", "run_router.py", "深淵"],
                router_argv=["深淵"],
                force_subprocess=False,
            )

        self.assertEqual(returncode, 0)
        in_process.assert_called_once_with(["深淵"])
        subprocess_run.assert_not_called()

    def test_run_router_task_force_subprocess_uses_old_mode_with_utf8_env(self):
        completed = subprocess.CompletedProcess(args=[], returncode=7)
        with patch.object(loop_afk, "run_router_task_in_process") as in_process, \
             patch("AwayFromKeyboard.loop_afk.subprocess.run", return_value=completed) as subprocess_run:
            returncode = loop_afk.run_router_task(
                task_cmd=["python", "run_router.py", "深淵"],
                router_argv=["深淵"],
                force_subprocess=True,
            )

        self.assertEqual(returncode, 7)
        in_process.assert_not_called()
        subprocess_run.assert_called_once()
        child_env = subprocess_run.call_args.kwargs["env"]
        self.assertEqual(child_env["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(child_env["PYTHONUTF8"], "1")

    def test_run_router_task_watchdog_uses_subprocess_watchdog_and_debug_label(self):
        recovery = MagicMock()
        watchdog = loop_afk.TaskWatchdogConfig(
            enabled=True,
            task_timeout_seconds=600,
            hard_timeout_seconds=1200,
            stuck_probe_seconds=60,
            stuck_probe_interval_seconds=10,
            debug_label="afk_test_label",
        )

        with patch.object(loop_afk, "run_router_task_subprocess_watchdog", return_value=(124, "stuck_static")) as run_watchdog, \
             patch.object(loop_afk, "rename_router_debug_dirs_for_failure") as rename_debug:
            returncode = loop_afk.run_router_task(
                task_cmd=["python", "run_router.py", "route_a"],
                router_argv=["route_a"],
                force_subprocess=False,
                watchdog=watchdog,
                recovery=recovery,
            )

        self.assertEqual(returncode, 124)
        run_watchdog.assert_called_once()
        env = run_watchdog.call_args.kwargs["env"]
        self.assertEqual(env["VL_ACTION_DEBUG_LABEL"], "afk_test_label")
        rename_debug.assert_called_once_with("afk_test_label", "stuck_static", 124)

    def test_run_router_task_route_exit_failure_renames_only_route_exit_debug_dir(self):
        recovery = MagicMock()
        watchdog = loop_afk.TaskWatchdogConfig(
            enabled=True,
            task_timeout_seconds=600,
            hard_timeout_seconds=1200,
            stuck_probe_seconds=60,
            stuck_probe_interval_seconds=10,
            debug_label="afk_test_label",
        )

        with patch.object(
            loop_afk,
            "run_router_task_subprocess_watchdog",
            return_value=(loop_afk.ROUTE_EXIT_AFTER_COMMAND_SUCCESS_RETURNCODE, "route_exit_after_task_success"),
        ), patch.object(loop_afk, "rename_router_debug_dirs_for_failure") as rename_debug:
            returncode = loop_afk.run_router_task(
                task_cmd=["python", "run_router.py", "route_a"],
                router_argv=["route_a"],
                force_subprocess=False,
                watchdog=watchdog,
                recovery=recovery,
            )

        self.assertEqual(returncode, loop_afk.ROUTE_EXIT_AFTER_COMMAND_SUCCESS_RETURNCODE)
        rename_debug.assert_called_once_with(
            "afk_test_label",
            "route_exit_after_task_success",
            loop_afk.ROUTE_EXIT_AFTER_COMMAND_SUCCESS_RETURNCODE,
        )

    def test_rename_latest_stage_action_debug_dir_for_failure_only_marks_active_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(loop_afk, "LOG_DIR", Path(tmpdir)):
                old = Path(tmpdir) / "20260711_010000_afk_label_route_enter"
                new = Path(tmpdir) / "20260711_010001_afk_label_task"
                old.mkdir()
                new.mkdir()
                os.utime(old, (1, 1))
                os.utime(new, (2, 2))

                renamed = loop_afk.rename_latest_stage_action_debug_dir_for_failure(
                    "afk_label",
                    "stuck_static",
                )

                self.assertEqual(len(renamed), 1)
                self.assertIn("_task_fail_stuck_static", renamed[0].name)
                self.assertTrue(old.exists())

    def test_run_router_task_in_process_converts_system_exit_to_returncode(self):
        with patch("AwayFromKeyboard.integration_task.run_router.main", side_effect=SystemExit(3)):
            self.assertEqual(loop_afk.run_router_task_in_process(["深淵"]), 3)

    def test_run_router_task_with_recovery_direct_retry_success(self):
        recovery = MagicMock()
        with patch.object(loop_afk, "run_router_task", side_effect=[1, 0]) as run_task, \
             patch.object(loop_afk, "restart_game_app_and_reenter") as restart_app, \
             patch.object(loop_afk, "restart_bluestacks_and_reenter") as restart_bs:
            returncode, stage = loop_afk.run_router_task_with_recovery(
                task_cmd=["python", "run_router.py", "route_a"],
                router_argv=["route_a"],
                force_subprocess=False,
                recovery=recovery,
                enabled=True,
                bluestacks_boot_wait_seconds=1,
            )

        self.assertEqual(returncode, 0)
        self.assertEqual(stage, "direct_retry")
        self.assertEqual(run_task.call_count, 2)
        restart_app.assert_not_called()
        restart_bs.assert_not_called()

    def test_run_router_task_with_recovery_route_exit_failure_does_not_rerun_task(self):
        recovery = MagicMock()
        recovery.recover_to_main.return_value = True
        with patch.object(
            loop_afk,
            "run_router_task",
            return_value=loop_afk.ROUTE_EXIT_AFTER_COMMAND_SUCCESS_RETURNCODE,
        ) as run_task, patch.object(loop_afk, "restart_game_app_and_reenter") as restart_app:
            returncode, stage = loop_afk.run_router_task_with_recovery(
                task_cmd=["python", "run_router.py", "route_a"],
                router_argv=["route_a"],
                force_subprocess=False,
                recovery=recovery,
                enabled=True,
                bluestacks_boot_wait_seconds=1,
            )

        self.assertEqual(returncode, 0)
        self.assertEqual(stage, "route_exit_recovered")
        run_task.assert_called_once()
        recovery.recover_to_main.assert_called_once()
        restart_app.assert_not_called()

    def test_run_router_task_with_recovery_restarts_app_then_bluestacks(self):
        recovery = MagicMock()
        with patch.object(loop_afk, "run_router_task", side_effect=[1, 1, 1, 0]) as run_task, \
             patch.object(loop_afk, "restart_game_app_and_reenter", return_value=True) as restart_app, \
             patch.object(loop_afk, "restart_bluestacks_and_reenter", return_value=True) as restart_bs:
            returncode, stage = loop_afk.run_router_task_with_recovery(
                task_cmd=["python", "run_router.py", "route_a"],
                router_argv=["route_a"],
                force_subprocess=False,
                recovery=recovery,
                enabled=True,
                bluestacks_boot_wait_seconds=123,
            )

        self.assertEqual(returncode, 0)
        self.assertEqual(stage, "bluestacks_restart_retry")
        self.assertEqual(run_task.call_count, 4)
        restart_app.assert_called_once_with(recovery)
        restart_bs.assert_called_once_with(recovery, boot_wait_seconds=123)

    def test_run_router_task_with_recovery_disabled_keeps_fail_fast_returncode(self):
        recovery = MagicMock()
        with patch.object(loop_afk, "run_router_task", return_value=1) as run_task, \
             patch.object(loop_afk, "restart_game_app_and_reenter") as restart_app:
            returncode, stage = loop_afk.run_router_task_with_recovery(
                task_cmd=["python", "run_router.py", "route_a"],
                router_argv=["route_a"],
                force_subprocess=False,
                recovery=recovery,
                enabled=False,
                bluestacks_boot_wait_seconds=1,
            )

        self.assertEqual(returncode, 1)
        self.assertEqual(stage, "initial")
        run_task.assert_called_once()
        restart_app.assert_not_called()

    def test_switch_account_with_recovery_disabled_uses_in_process_switch(self):
        recovery = MagicMock()
        watchdog = loop_afk.TaskWatchdogConfig(
            enabled=False,
            task_timeout_seconds=600,
            hard_timeout_seconds=1200,
            stuck_probe_seconds=60,
            stuck_probe_interval_seconds=10,
        )

        with patch.object(loop_afk, "switch_account", return_value=True) as switch_mock, \
             patch.object(loop_afk, "run_switch_account_command") as run_switch:
            success, stage = loop_afk.switch_account_with_recovery(
                account_name="em3",
                switch_cmd=["python", "-m", "switch_account.switch_account", "em3"],
                recovery=recovery,
                enabled=False,
                bluestacks_boot_wait_seconds=180,
                watchdog=watchdog,
            )

        self.assertTrue(success)
        self.assertEqual(stage, "initial")
        switch_mock.assert_called_once_with("em3")
        run_switch.assert_not_called()

    def test_switch_account_with_recovery_fails_after_app_and_bluestacks_retry(self):
        recovery = MagicMock()
        watchdog = loop_afk.TaskWatchdogConfig(
            enabled=True,
            task_timeout_seconds=600,
            hard_timeout_seconds=1200,
            stuck_probe_seconds=60,
            stuck_probe_interval_seconds=10,
            debug_label="afk_switch",
        )

        with patch.object(
            loop_afk,
            "run_switch_account_command",
            side_effect=[(False, "stuck_static"), (False, "returncode_1"), (False, "returncode_1")],
        ) as run_switch, \
             patch.object(loop_afk, "restart_game_app_and_reenter", return_value=True) as restart_app, \
             patch.object(loop_afk, "restart_bluestacks_and_reenter", return_value=True) as restart_bs:
            success, stage = loop_afk.switch_account_with_recovery(
                account_name="em3",
                switch_cmd=["python", "-m", "switch_account.switch_account", "em3"],
                recovery=recovery,
                enabled=True,
                bluestacks_boot_wait_seconds=180,
                watchdog=watchdog,
            )

        self.assertFalse(success)
        self.assertEqual(stage, "returncode_1")
        self.assertEqual(run_switch.call_count, 3)
        restart_app.assert_called_once_with(recovery)
        restart_bs.assert_called_once_with(recovery, boot_wait_seconds=180)

    def test_resolve_task_watchdog_config_uses_ini_timeout_and_double_hard_timeout(self):
        config = loop_afk.resolve_task_watchdog_config(
            enabled=True,
            account_name="em3",
            task_name="route_a",
            cli_task_timeout_seconds=600,
            cli_hard_timeout_seconds=1200,
            stuck_probe_seconds=60,
            stuck_probe_interval_seconds=10,
            ini_timeout="00:03:00",
            ini_hard_timeout=None,
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.task_timeout_seconds, 180)
        self.assertEqual(config.hard_timeout_seconds, 360)
        self.assertIn("em3", config.debug_label)

    def test_task_config_reads_task_timeouts_from_ini(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom.ini"
            config_path.write_text(
                "[route_a]\n"
                "enable = Y\n"
                "timeout = 00:03:00\n"
                "hard_timeout = 00:07:00\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"AFK_TASKS_INI": str(config_path)}):
                self.assertEqual(task_config.get_task_timeout("route_a"), "00:03:00")
                self.assertEqual(task_config.get_task_hard_timeout("route_a"), "00:07:00")

    def test_cleanup_previous_day_logs_removes_only_yesterday_log_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            yesterday_file = log_dir / "20260702_090000_route_每日任務.txt"
            yesterday_afk_file = log_dir / "afk_20260702_090000_em3_每日任務.txt"
            yesterday_dir = log_dir / "20260702_090000_route_疾風呼喚"
            today_file = log_dir / "afk_20260703_090000_em3_每日任務.txt"
            unrelated_file = log_dir / "profile_latest.txt"

            yesterday_file.write_text("old", encoding="utf-8")
            yesterday_afk_file.write_text("old", encoding="utf-8")
            yesterday_dir.mkdir()
            (yesterday_dir / "screen.png").write_text("old", encoding="utf-8")
            today_file.write_text("new", encoding="utf-8")
            unrelated_file.write_text("keep", encoding="utf-8")

            removed = loop_afk.cleanup_previous_day_logs(
                log_dir,
                now=datetime(2026, 7, 3, 9, 0, 0, tzinfo=loop_afk.TAIPEI_TZ),
            )

            self.assertEqual(removed, 3)
            self.assertFalse(yesterday_file.exists())
            self.assertFalse(yesterday_afk_file.exists())
            self.assertFalse(yesterday_dir.exists())
            self.assertTrue(today_file.exists())
            self.assertTrue(unrelated_file.exists())

    def test_previous_log_date_prefix_uses_taipei_calendar_day(self):
        self.assertEqual(
            loop_afk.previous_log_date_prefix(
                datetime(2026, 7, 3, 1, 0, 0, tzinfo=loop_afk.TAIPEI_TZ)
            ),
            "20260702",
        )

    def test_record_current_account_writes_non_empty_account_only(self):
        with patch("AwayFromKeyboard.loop_afk.write_current_account") as write:
            loop_afk.record_current_account("311", "test.source")
            loop_afk.record_current_account(None, "test.none")

        write.assert_called_once_with("311", source="test.source")

    def test_is_midas_activity_active_only_for_active_midas_auto(self):
        with patch("AwayFromKeyboard.loop_afk.read_activity_state", return_value={"activity": "midas_auto", "active": True}):
            self.assertTrue(loop_afk.is_midas_activity_active())

        with patch("AwayFromKeyboard.loop_afk.read_activity_state", return_value={"activity": "midas_auto", "active": False}):
            self.assertFalse(loop_afk.is_midas_activity_active())

        with patch("AwayFromKeyboard.loop_afk.read_activity_state", return_value={"activity": "other", "active": True}):
            self.assertFalse(loop_afk.is_midas_activity_active())

    def test_midas_activity_wait_reason_detects_wake_guard_window(self):
        now = datetime(2026, 7, 3, 7, 45, 0, tzinfo=loop_afk.TAIPEI_TZ)

        self.assertEqual(
            loop_afk.midas_activity_wait_reason(
                {
                    "activity": "midas_auto",
                    "active": False,
                    "wake_at": "2026-07-03T08:00:00+08:00",
                },
                now=now,
            ),
            "wake_soon",
        )

    def test_midas_activity_wait_reason_treats_active_lock_over_10_minutes_as_stale(self):
        now = datetime(2026, 7, 3, 8, 11, 0, tzinfo=loop_afk.TAIPEI_TZ)

        self.assertEqual(
            loop_afk.midas_activity_wait_reason(
                {
                    "activity": "midas_auto",
                    "active": True,
                    "updated_at": "2026-07-03T08:00:00+08:00",
                },
                now=now,
            ),
            "stale_active",
        )

    def test_midas_activity_wait_reason_keeps_recent_active_lock(self):
        now = datetime(2026, 7, 3, 8, 9, 0, tzinfo=loop_afk.TAIPEI_TZ)

        self.assertEqual(
            loop_afk.midas_activity_wait_reason(
                {
                    "activity": "midas_auto",
                    "active": True,
                    "updated_at": "2026-07-03T08:00:00+08:00",
                },
                now=now,
            ),
            "active",
        )

    def test_midas_activity_wait_reason_ignores_far_future_and_stale_wake_time(self):
        self.assertIsNone(
            loop_afk.midas_activity_wait_reason(
                {
                    "activity": "midas_auto",
                    "active": False,
                    "wake_at": "2026-07-03T08:00:00+08:00",
                },
                now=datetime(2026, 7, 3, 7, 30, 0, tzinfo=loop_afk.TAIPEI_TZ),
            )
        )
        self.assertIsNone(
            loop_afk.midas_activity_wait_reason(
                {
                    "activity": "midas_auto",
                    "active": False,
                    "wake_at": "2026-07-03T08:00:00+08:00",
                },
                now=datetime(2026, 7, 3, 10, 1, 0, tzinfo=loop_afk.TAIPEI_TZ),
            )
        )

    @patch("AwayFromKeyboard.loop_afk.smart_sleep")
    def test_wait_for_midas_activity_clearance_polls_until_state_clears(self, sleep_mock):
        recovery = MagicMock()
        states = [
            {"activity": "midas_auto", "active": True},
            {
                "activity": "midas_auto",
                "active": False,
                "wake_at": "2026-07-03T08:00:00+08:00",
            },
            {"activity": "midas_auto", "active": False},
        ]

        with patch("AwayFromKeyboard.loop_afk.read_activity_state", side_effect=states), \
             patch(
                 "AwayFromKeyboard.loop_afk.midas_activity_wait_reason",
                 side_effect=["active", "wake_soon", None],
             ):
            loop_afk.wait_for_midas_activity_clearance(recovery, notify_enabled=False)

        self.assertEqual(sleep_mock.call_count, 2)
        sleep_mock.assert_called_with(loop_afk.MIDAS_ACTIVITY_POLL_SECONDS)
        self.assertEqual(recovery.recover_to_main.call_count, 2)

    @patch("AwayFromKeyboard.loop_afk.notify_status")
    @patch("AwayFromKeyboard.loop_afk.smart_sleep")
    def test_wait_for_midas_activity_clearance_ignores_stale_active_lock(self, sleep_mock, notify_mock):
        recovery = MagicMock()
        with patch("AwayFromKeyboard.loop_afk.read_activity_state", return_value={"activity": "midas_auto", "active": True}), \
             patch("AwayFromKeyboard.loop_afk.midas_activity_wait_reason", return_value="stale_active"):
            loop_afk.wait_for_midas_activity_clearance(recovery, notify_enabled=True)

        sleep_mock.assert_not_called()
        recovery.recover_to_main.assert_not_called()
        notify_mock.assert_called_once()

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


    def test_task_config_includes_route_only_task_with_empty_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom.ini"
            config_path.write_text(
                "[route_only]\n"
                "enable = Y\n"
                "command = \n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"AFK_TASKS_INI": str(config_path)}):
                self.assertEqual(task_config.get_tasks_to_run(), ["route_only"])
                self.assertEqual(task_config.get_command_for_task("route_only"), [])


if __name__ == "__main__":
    unittest.main()
