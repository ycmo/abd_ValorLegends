import unittest

import numpy as np

from src.adb_controller import DeviceController


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


if __name__ == "__main__":
    unittest.main()
