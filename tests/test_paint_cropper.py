from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from src.paint_cropper import (
    crop_inside_blue_box,
    crop_inside_colored_box,
    find_blue_boxes,
    find_green_boxes,
    find_red_boxes,
    run_paint_crop_workflow,
    write_blue_crop_review,
)
from src.vision_matcher import write_image

PAINT_BLUE = (204, 72, 63)


class PaintCropperTests(unittest.TestCase):
    def test_find_blue_boxes_detects_multiple_outline_rectangles(self):
        image = np.full((120, 220, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (20, 15), (90, 70), PAINT_BLUE, 2)
        cv2.rectangle(image, (120, 30), (190, 95), PAINT_BLUE, 2)
        cv2.rectangle(image, (5, 5), (12, 12), PAINT_BLUE, -1)

        boxes = find_blue_boxes(image)

        self.assertEqual(len(boxes), 2)
        self.assertEqual([(box.x, box.y) for box in boxes], [(19, 14), (119, 29)])

    def test_find_blue_boxes_accepts_button_like_partial_side_edges(self):
        image = np.full((80, 200, 3), 255, dtype=np.uint8)
        cv2.line(image, (20, 20), (170, 20), PAINT_BLUE, 3)
        cv2.line(image, (20, 55), (170, 55), PAINT_BLUE, 3)
        cv2.line(image, (20, 20), (20, 55), PAINT_BLUE, 1)
        cv2.line(image, (170, 20), (170, 55), PAINT_BLUE, 1)

        boxes = find_blue_boxes(image)

        self.assertEqual(len(boxes), 1)
        self.assertEqual((boxes[0].x, boxes[0].y, boxes[0].width, boxes[0].height), (18, 18, 155, 40))

    def test_crop_inside_blue_box_removes_blue_border(self):
        image = np.full((80, 100, 3), 255, dtype=np.uint8)
        image[25:55, 30:70] = (10, 20, 30)
        cv2.rectangle(image, (28, 23), (72, 57), PAINT_BLUE, 2)

        box = find_blue_boxes(image)[0]
        crop = crop_inside_blue_box(image, box)

        self.assertGreater(crop.shape[0], 20)
        self.assertGreater(crop.shape[1], 30)
        self.assertFalse(np.any(np.all(crop == PAINT_BLUE, axis=2)))

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

    def test_find_blue_boxes_accepts_small_digit_box(self):
        image = np.full((80, 120, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (48, 30), (68, 53), PAINT_BLUE, 3)

        boxes = find_blue_boxes(image)

        self.assertEqual(len(boxes), 1)
        self.assertLessEqual(abs(boxes[0].width - 23), 2)
        self.assertLessEqual(abs(boxes[0].height - 26), 2)

    def test_find_blue_boxes_accepts_tiny_notification_marker_box(self):
        image = np.full((80, 120, 3), 255, dtype=np.uint8)
        image[25:35, 45:52] = (20, 30, 40)
        cv2.rectangle(image, (40, 20), (56, 39), PAINT_BLUE, 2)

        boxes = find_blue_boxes(image)

        self.assertEqual(len(boxes), 1)
        self.assertLessEqual(abs(boxes[0].width - 19), 2)
        self.assertLessEqual(abs(boxes[0].height - 22), 2)
        crop = crop_inside_blue_box(image, boxes[0])
        self.assertGreater(crop.shape[0], 5)
        self.assertGreater(crop.shape[1], 5)
        self.assertFalse(np.any(np.all(crop == PAINT_BLUE, axis=2)))

    def test_find_red_boxes_detects_click_region_outline(self):
        image = np.full((100, 180, 3), 255, dtype=np.uint8)
        image[34:72, 48:138] = (40, 80, 120)
        cv2.rectangle(image, (44, 30), (142, 76), (0, 0, 255), 3)

        boxes = find_red_boxes(image)

        self.assertEqual(len(boxes), 1)
        crop = crop_inside_colored_box(image, boxes[0], "red")
        self.assertGreater(crop.shape[0], 30)
        self.assertGreater(crop.shape[1], 70)
        self.assertFalse(np.any(np.all(crop == (0, 0, 255), axis=2)))

    def test_find_green_boxes_detects_recognition_anchor_outline(self):
        image = np.full((100, 180, 3), 255, dtype=np.uint8)
        image[34:72, 48:138] = (50, 90, 130)
        cv2.rectangle(image, (44, 30), (142, 76), (0, 180, 0), 3)

        boxes = find_green_boxes(image)

        self.assertEqual(len(boxes), 1)
        crop = crop_inside_colored_box(image, boxes[0], "green")
        self.assertGreater(crop.shape[0], 30)
        self.assertGreater(crop.shape[1], 70)
        self.assertFalse(np.any(np.all(crop == (0, 180, 0), axis=2)))

    def test_write_blue_crop_review_outputs_serial_files_manifest_and_sheet(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = np.full((120, 220, 3), 255, dtype=np.uint8)
            cv2.rectangle(image, (20, 15), (90, 70), PAINT_BLUE, 2)
            cv2.rectangle(image, (120, 30), (190, 95), PAINT_BLUE, 2)
            source = root / "001_起始.png"
            write_image(source, image)

            saved = write_blue_crop_review([source], root / "review", source_folder=root)

            self.assertEqual([path.name for path in saved], [
                "001_screen01_blue01_19_14_73x58.png",
                "002_screen01_blue02_119_29_73x68.png",
            ])
            self.assertTrue((root / "review" / "000_contact_sheet.png").exists())
            manifest = (root / "review" / "manifest.txt").read_text(encoding="utf-8")
            self.assertIn("001: file=001_screen01_blue01_19_14_73x58.png source=001_起始.png", manifest)
            self.assertIn("002: file=002_screen01_blue02_119_29_73x68.png source=001_起始.png", manifest)

    def test_run_paint_crop_workflow_does_not_keep_serial_review_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = np.full((90, 160, 3), 255, dtype=np.uint8)
            cv2.rectangle(image, (30, 20), (120, 60), PAINT_BLUE, 2)
            source = root / "001_起始.png"
            write_image(source, image)

            saved = run_paint_crop_workflow(
                source,
                input_func=lambda prompt: "",
                paint_runner=lambda path: None,
            )

            self.assertEqual(saved, [])
            self.assertFalse((root / "000_contact_sheet.png").exists())
            self.assertFalse((root / "manifest.txt").exists())
            self.assertFalse(any(path.name.startswith("001_screen01_blue01_") for path in root.glob("*.png")))


if __name__ == "__main__":
    unittest.main()
