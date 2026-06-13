from __future__ import annotations

import unittest

import cv2
import numpy as np

from src.paint_cropper import crop_inside_blue_box, find_blue_boxes


class PaintCropperTests(unittest.TestCase):
    def test_find_blue_boxes_detects_multiple_outline_rectangles(self):
        image = np.full((120, 220, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (20, 15), (90, 70), (255, 0, 0), 2)
        cv2.rectangle(image, (120, 30), (190, 95), (255, 0, 0), 2)
        cv2.rectangle(image, (5, 5), (12, 12), (255, 0, 0), -1)

        boxes = find_blue_boxes(image)

        self.assertEqual(len(boxes), 2)
        self.assertEqual([(box.x, box.y) for box in boxes], [(19, 14), (119, 29)])

    def test_crop_inside_blue_box_removes_blue_border(self):
        image = np.full((80, 100, 3), 255, dtype=np.uint8)
        image[25:55, 30:70] = (10, 20, 30)
        cv2.rectangle(image, (28, 23), (72, 57), (255, 0, 0), 2)

        box = find_blue_boxes(image)[0]
        crop = crop_inside_blue_box(image, box)

        self.assertGreater(crop.shape[0], 20)
        self.assertGreater(crop.shape[1], 30)
        self.assertFalse(np.any(np.all(crop == (255, 0, 0), axis=2)))

    def test_find_blue_boxes_detects_paint_dark_blue_outline(self):
        image = np.full((90, 180, 3), (35, 35, 60), dtype=np.uint8)
        image[28:62, 38:142] = (7, 180, 245)
        cv2.rectangle(image, (34, 24), (146, 66), (204, 72, 63), 3)

        boxes = find_blue_boxes(image)

        self.assertEqual(len(boxes), 1)
        box = boxes[0]
        self.assertLessEqual(abs(box.x - 33), 2)
        self.assertLessEqual(abs(box.y - 23), 2)
        self.assertLessEqual(abs(box.width - 116), 4)
        self.assertLessEqual(abs(box.height - 46), 4)


if __name__ == "__main__":
    unittest.main()
