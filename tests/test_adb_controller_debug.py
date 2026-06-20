import unittest
from unittest.mock import patch

import numpy as np

from src.adb_controller import AdbControllerError, DeviceController


class AdbControllerDebugAnnotationTests(unittest.TestCase):
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

        with patch.object(controller, "_run", side_effect=AdbControllerError("missing")), \
             patch.object(DeviceController, "_try_adb_connect") as connect_probe, \
             patch.object(DeviceController, "list_devices", return_value=["127.0.0.1:5555"]):
            self.assertTrue(controller.connect())

        connect_probe.assert_called_once_with("127.0.0.1:5555")
        self.assertEqual(controller.serial, "127.0.0.1:5555")

    def test_select_fallback_serial_prefers_localhost_bluestacks(self):
        selected = DeviceController._select_fallback_serial(["emulator-5554", "127.0.0.1:5555"])
        self.assertEqual(selected, "127.0.0.1:5555")


if __name__ == "__main__":
    unittest.main()
