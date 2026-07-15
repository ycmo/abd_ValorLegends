import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_router


class RunRouterCommandTests(unittest.TestCase):
    def test_detects_src_main_command(self):
        self.assertTrue(run_router._is_src_main_command(["-m", "src.main", "--debug", "run-all"]))
        self.assertFalse(run_router._is_src_main_command(["call_of_the_gale/scripts/auto_shoot.py"]))

    def test_prepare_src_main_argv_adds_serial_without_forcing_debug_actions(self):
        argv = run_router._prepare_src_main_argv(
            ["-m", "src.main", "--debug", "run-all"],
            selected_serial="emulator-1234",
        )

        self.assertEqual(argv, ["--serial", "emulator-1234", "--debug", "run-all"])

    def test_prepare_src_main_argv_keeps_explicit_serial(self):
        argv = run_router._prepare_src_main_argv(
            ["-m", "src.main", "--serial", "explicit", "run-all"],
            selected_serial="emulator-1234",
        )

        self.assertEqual(argv, ["--serial", "explicit", "run-all"])

    def test_prepare_src_main_argv_preserves_ini_debug_actions(self):
        argv = run_router._prepare_src_main_argv(
            ["-m", "src.main", "--debug", "--debug-actions", "run-all"],
            selected_serial=None,
        )

        self.assertEqual(argv, ["--debug", "--debug-actions", "run-all"])

    def test_profile_log_file_uses_route_log_stem(self):
        path = run_router._profile_log_file_for_route_log(r"E:\debug\afk_每日任務.txt")

        self.assertEqual(path, r"E:\debug\afk_每日任務.profile.txt")

    def test_src_main_command_runs_in_process_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.main", return_value=0) as mock_main, \
                 patch("run_router.subprocess.run") as mock_subprocess:
                returncode = run_router.run_configured_command(
                    ["-m", "src.main", "--debug", "run-all"],
                    project_root=Path(tmpdir),
                    python_exe="python",
                    selected_serial="emulator-1234",
                    route_debug_label="route_test",
                    debug_actions=True,
                    force_subprocess=False,
                    profile_log_file=str(Path(tmpdir) / "route.profile.txt"),
                )

        self.assertEqual(returncode, 0)
        mock_main.assert_called_once_with(["--serial", "emulator-1234", "--debug", "run-all"])
        mock_subprocess.assert_not_called()

    def test_src_main_in_process_restores_environment(self):
        old_serial = os.environ.get("VL_ADB_SERIAL")
        old_debug = os.environ.get("VL_DEBUG_ACTIONS")
        old_label = os.environ.get("VL_ACTION_DEBUG_LABEL")
        old_profile = os.environ.get("VL_PROFILE_LOG_FILE")
        old_pythonioencoding = os.environ.get("PYTHONIOENCODING")
        old_pythonutf8 = os.environ.get("PYTHONUTF8")
        old_pythonunbuffered = os.environ.get("PYTHONUNBUFFERED")
        observed = {}

        def fake_main(_argv):
            observed["serial"] = os.environ.get("VL_ADB_SERIAL")
            observed["debug"] = os.environ.get("VL_DEBUG_ACTIONS")
            observed["label"] = os.environ.get("VL_ACTION_DEBUG_LABEL")
            observed["profile"] = os.environ.get("VL_PROFILE_LOG_FILE")
            observed["pythonioencoding"] = os.environ.get("PYTHONIOENCODING")
            observed["pythonutf8"] = os.environ.get("PYTHONUTF8")
            observed["pythonunbuffered"] = os.environ.get("PYTHONUNBUFFERED")
            return 0

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = str(Path(tmpdir) / "route.profile.txt")
            with patch("src.main.main", side_effect=fake_main):
                returncode = run_router.run_configured_command(
                    ["-m", "src.main", "run-all"],
                    project_root=Path(tmpdir),
                    python_exe="python",
                    selected_serial="emulator-5678",
                    route_debug_label="route_test",
                    debug_actions=True,
                    force_subprocess=False,
                    profile_log_file=profile_path,
                )

        self.assertEqual(returncode, 0)
        self.assertEqual(
            observed,
            {
                "serial": "emulator-5678",
                "debug": None,
                "label": "route_test",
                "profile": profile_path,
                "pythonioencoding": "utf-8",
                "pythonutf8": "1",
                "pythonunbuffered": "1",
            },
        )
        self.assertEqual(os.environ.get("VL_ADB_SERIAL"), old_serial)
        self.assertEqual(os.environ.get("VL_DEBUG_ACTIONS"), old_debug)
        self.assertEqual(os.environ.get("VL_ACTION_DEBUG_LABEL"), old_label)
        self.assertEqual(os.environ.get("VL_PROFILE_LOG_FILE"), old_profile)
        self.assertEqual(os.environ.get("PYTHONIOENCODING"), old_pythonioencoding)
        self.assertEqual(os.environ.get("PYTHONUTF8"), old_pythonutf8)
        self.assertEqual(os.environ.get("PYTHONUNBUFFERED"), old_pythonunbuffered)

    def test_force_subprocess_keeps_old_execution_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.main") as mock_main, \
                 patch("run_router._run_subprocess_streamed", return_value=7) as mock_subprocess:
                returncode = run_router.run_configured_command(
                    ["-m", "src.main", "run-all"],
                    project_root=Path(tmpdir),
                    python_exe="python",
                    selected_serial="emulator-1234",
                    route_debug_label="route_test",
                    debug_actions=False,
                    force_subprocess=True,
                )

        self.assertEqual(returncode, 7)
        mock_main.assert_not_called()
        mock_subprocess.assert_called_once()

    def test_external_command_still_uses_subprocess(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("run_router._run_subprocess_streamed", return_value=0) as mock_subprocess:
                returncode = run_router.run_configured_command(
                    ["call_of_the_gale/scripts/auto_shoot.py"],
                    project_root=Path(tmpdir),
                    python_exe="python",
                    selected_serial=None,
                    route_debug_label="route_test",
                    debug_actions=False,
                    force_subprocess=False,
                    profile_log_file=str(Path(tmpdir) / "route.profile.txt"),
                )

        self.assertEqual(returncode, 0)
        mock_subprocess.assert_called_once()
        child_env = mock_subprocess.call_args.kwargs["env"]
        self.assertEqual(child_env["VL_PROFILE_LOG_FILE"], str(Path(tmpdir) / "route.profile.txt"))
        self.assertEqual(child_env["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(child_env["PYTHONUTF8"], "1")
        self.assertEqual(child_env["PYTHONUNBUFFERED"], "1")

    def test_route_only_task_runs_enter_and_exit_routes(self):
        with patch("run_router.warn_if_midas_activity_active"), \
             patch("run_router.task_config.get_command_for_task", return_value=[]), \
             patch("run_router.RouteNavigator") as navigator_class, \
             patch("sys.stdout", new=StringIO()):
            navigator = navigator_class.return_value

            run_router.main(["每日簽到"])

        navigator.execute_route.assert_any_call(phase="enter")
        navigator.execute_route.assert_any_call(phase="exit")
        self.assertEqual(navigator.execute_route.call_count, 2)

    def test_tee_output_writes_utf8_log_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "router.log"
            with run_router._tee_output(str(path)):
                print("每日任務 測試")

            self.assertIn("每日任務 測試", path.read_text(encoding="utf-8"))

    def test_tee_stream_flushes_line_buffered_output(self):
        class TrackingStream(StringIO):
            def __init__(self):
                super().__init__()
                self.flushes = 0

            def flush(self):
                self.flushes += 1
                super().flush()

        console = TrackingStream()
        log = TrackingStream()
        stream = run_router._TeeStream(console, log)

        stream.write("partial")
        self.assertEqual(console.flushes, 0)
        self.assertEqual(log.flushes, 0)

        stream.write("line\n")
        self.assertEqual(console.flushes, 1)
        self.assertEqual(log.flushes, 1)


if __name__ == "__main__":
    unittest.main()
