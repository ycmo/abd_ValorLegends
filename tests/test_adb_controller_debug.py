import unittest
import subprocess
from unittest.mock import patch

import cv2
import numpy as np

from src.adb_controller import AdbControllerError, DeviceController


class AdbControllerDebugAnnotationTests(unittest.TestCase):
    def test_debug_dir_appends_sanitized_label(self):
        controller = DeviceController(debug_actions=True, debug_label="abyss route/magic_store")

        self.assertRegex(
            controller.debug_dir.name,
            r"^\d{8}_\d{6}_\d+_abyss_route_magic_store$",
        )

    def test_annotate_action_debug_image_draws_tap_and_boxes(self):
        image = np.zeros((220, 260, 3), dtype=np.uint8)

        annotated = DeviceController._annotate_action_debug_image(
            image,
            tap_point=(180, 150),
            debug_lines=["daily task: arena", "label task_label_wide.png conf=0.980"],
            debug_boxes=[
                (20, 90, 50, 20, "label"),
                (100, 95, 60, 35, "status_roi"),
                (112, 103, 32, 18, "go"),
            ],
        )

        self.assertEqual(annotated.shape, image.shape)
        self.assertGreater(np.count_nonzero(annotated), 0)
        self.assertTrue(np.any(np.all(annotated == (0, 0, 255), axis=2)))
        self.assertTrue(np.any(np.all(annotated == (0, 255, 0), axis=2)))

    def test_annotate_action_debug_image_draws_swipe_arrow(self):
        image = np.zeros((220, 260, 3), dtype=np.uint8)

        annotated = DeviceController._annotate_action_debug_image(
            image,
            swipe_points=((40, 180), (180, 60)),
            debug_lines=["action=swipe_40_180_180_60_520"],
        )

        self.assertEqual(annotated.shape, image.shape)
        self.assertGreater(np.count_nonzero(annotated), 0)
        self.assertTrue(np.any(np.all(annotated == (0, 0, 255), axis=2)))

    def test_action_debug_lines_names_back_keyevent(self):
        self.assertEqual(DeviceController._action_debug_lines("keyevent_4"), ["action=keyevent BACK"])
        self.assertEqual(DeviceController._tap_point_from_action_name("tap_123_456"), (123, 456))
        self.assertEqual(
            DeviceController._swipe_points_from_action_name("swipe_1_2_3_4_500"),
            ((1, 2), (3, 4)),
        )

    def test_screenshot_does_not_save_bare_action_debug_image(self):
        controller = DeviceController(debug_actions=True)
        image = np.zeros((20, 20, 3), dtype=np.uint8)

        with patch.object(controller, "_capture_screen", return_value=image), \
             patch.object(controller, "_save_debug_image") as save_debug:
            result = controller.screenshot()

        self.assertIs(result, image)
        save_debug.assert_not_called()

    def test_connect_falls_back_to_connected_bluestacks_serial(self):
        controller = DeviceController(serial="emulator-5554")

        with patch.object(DeviceController, "_raw_get_state", return_value=False), \
             patch.object(DeviceController, "_try_adb_connect") as connect_probe, \
             patch.object(DeviceController, "_reset_adb_server") as reset_server, \
             patch.object(DeviceController, "list_devices", return_value=["127.0.0.1:5555"]):
            self.assertTrue(controller.connect())

        connect_probe.assert_called_once_with("127.0.0.1:5555")
        reset_server.assert_not_called()
        self.assertEqual(controller.serial, "127.0.0.1:5555")

    def test_connect_resets_adb_server_when_no_device_is_visible(self):
        controller = DeviceController(serial="emulator-5554")

        with patch.object(DeviceController, "_raw_get_state", return_value=False), \
             patch.object(DeviceController, "_try_adb_connect") as connect_probe, \
             patch.object(DeviceController, "_reset_adb_server", return_value=True) as reset_server, \
             patch.object(DeviceController, "list_devices", side_effect=[[], [], ["127.0.0.1:5555"]]):
            self.assertTrue(controller.connect())

        self.assertEqual(connect_probe.call_count, 3)
        reset_server.assert_called_once()
        self.assertEqual(controller.serial, "127.0.0.1:5555")

    def test_connect_uses_raw_get_state_without_recursive_reconnect(self):
        controller = DeviceController(serial="physical-device")

        with patch.object(DeviceController, "_raw_get_state", return_value=True) as raw_get_state, \
             patch.object(DeviceController, "_connect_available_fallback_device") as fallback:
            self.assertTrue(controller.connect())

        raw_get_state.assert_called_once_with("physical-device")
        fallback.assert_not_called()

    def test_connect_prefers_localhost_bluestacks_before_emulator_serial(self):
        controller = DeviceController(serial="emulator-5554")

        with patch.object(DeviceController, "_try_adb_connect"), \
             patch.object(DeviceController, "list_devices", return_value=["emulator-5554", "127.0.0.1:5555"]), \
             patch.object(DeviceController, "_raw_get_state") as raw_get_state:
            self.assertTrue(controller.connect())

        raw_get_state.assert_not_called()
        self.assertEqual(controller.serial, "127.0.0.1:5555")

    def test_select_fallback_serial_prefers_localhost_bluestacks(self):
        selected = DeviceController._select_fallback_serial(["emulator-5554", "127.0.0.1:5555"])
        self.assertEqual(selected, "127.0.0.1:5555")

    def test_run_reconnects_once_when_serial_disappears(self):
        controller = DeviceController(serial="emulator-5554")
        calls = [
            subprocess.CompletedProcess(
                ["adb"],
                1,
                stdout="",
                stderr="adb.exe: device 'emulator-5554' not found",
            ),
            subprocess.CompletedProcess(["adb"], 0, stdout="ok", stderr=""),
        ]

        with patch("src.adb_controller.subprocess.run", side_effect=calls) as run_cmd, \
             patch.object(controller, "connect", return_value=True) as connect:
            result = controller._run(["get-state"])

        self.assertEqual(result.stdout, "ok")
        connect.assert_called_once()
        self.assertEqual(run_cmd.call_count, 2)

    def test_screenshot_reconnects_once_when_serial_disappears(self):
        controller = DeviceController(serial="emulator-5554")
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        calls = [
            subprocess.CompletedProcess(
                ["adb"],
                1,
                stdout=b"",
                stderr=b"adb.exe: device 'emulator-5554' not found",
            ),
            subprocess.CompletedProcess(["adb"], 0, stdout=encoded.tobytes(), stderr=b""),
        ]

        with patch("src.adb_controller.subprocess.run", side_effect=calls), \
             patch.object(controller, "connect", return_value=True) as connect:
            screen = controller.screenshot()

        connect.assert_called_once()
        self.assertEqual(screen.shape, image.shape)


if __name__ == "__main__":
    unittest.main()
