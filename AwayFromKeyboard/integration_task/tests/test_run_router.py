import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_router


class RunRouterCommandTests(unittest.TestCase):
    def test_detects_src_main_command(self):
        self.assertTrue(run_router._is_src_main_command(["-m", "src.main", "--debug", "run-all"]))
        self.assertFalse(run_router._is_src_main_command(["call_of_the_gale/scripts/auto_shoot.py"]))

    def test_prepare_src_main_argv_adds_serial_and_debug_actions(self):
        argv = run_router._prepare_src_main_argv(
            ["-m", "src.main", "--debug", "run-all"],
            selected_serial="emulator-1234",
            debug_actions=True,
        )

        self.assertEqual(argv, ["--debug-actions", "--serial", "emulator-1234", "--debug", "run-all"])

    def test_prepare_src_main_argv_keeps_explicit_serial(self):
        argv = run_router._prepare_src_main_argv(
            ["-m", "src.main", "--serial", "explicit", "run-all"],
            selected_serial="emulator-1234",
            debug_actions=False,
        )

        self.assertEqual(argv, ["--serial", "explicit", "run-all"])

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
                )

        self.assertEqual(returncode, 0)
        mock_main.assert_called_once_with(["--debug-actions", "--serial", "emulator-1234", "--debug", "run-all"])
        mock_subprocess.assert_not_called()

    def test_src_main_in_process_restores_environment(self):
        old_serial = os.environ.get("VL_ADB_SERIAL")
        old_debug = os.environ.get("VL_DEBUG_ACTIONS")
        old_label = os.environ.get("VL_ACTION_DEBUG_LABEL")
        observed = {}

        def fake_main(_argv):
            observed["serial"] = os.environ.get("VL_ADB_SERIAL")
            observed["debug"] = os.environ.get("VL_DEBUG_ACTIONS")
            observed["label"] = os.environ.get("VL_ACTION_DEBUG_LABEL")
            return 0

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.main", side_effect=fake_main):
                returncode = run_router.run_configured_command(
                    ["-m", "src.main", "run-all"],
                    project_root=Path(tmpdir),
                    python_exe="python",
                    selected_serial="emulator-5678",
                    route_debug_label="route_test",
                    debug_actions=True,
                    force_subprocess=False,
                )

        self.assertEqual(returncode, 0)
        self.assertEqual(observed, {"serial": "emulator-5678", "debug": "1", "label": "route_test"})
        self.assertEqual(os.environ.get("VL_ADB_SERIAL"), old_serial)
        self.assertEqual(os.environ.get("VL_DEBUG_ACTIONS"), old_debug)
        self.assertEqual(os.environ.get("VL_ACTION_DEBUG_LABEL"), old_label)

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
                )

        self.assertEqual(returncode, 0)
        mock_subprocess.assert_called_once()

    def test_tee_output_writes_utf8_log_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "router.log"
            with run_router._tee_output(str(path)):
                print("每日任務 測試")

            self.assertIn("每日任務 測試", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
