import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.vision_matcher import VisionMatcher, clear_template_cache, write_image


class VisionMatcherTests(unittest.TestCase):
    def setUp(self):
        clear_template_cache()

    def tearDown(self):
        clear_template_cache()

    def test_match_template_all_returns_distinct_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.png"
            template = np.zeros((12, 18, 3), dtype=np.uint8)
            template[:, :] = (20, 120, 220)
            cv2.line(template, (2, 2), (15, 9), (250, 250, 250), 2)
            write_image(template_path, template)

            screen = np.zeros((80, 120, 3), dtype=np.uint8)
            screen[10:22, 20:38] = template
            screen[48:60, 70:88] = template

            matches = VisionMatcher().match_template_all(
                screen,
                template_path,
                threshold=0.99,
                min_center_distance=20,
            )

        self.assertEqual(len(matches), 2)
        self.assertEqual([match.center for match in matches], [(29, 16), (79, 54)])

    def test_template_is_loaded_once_for_unchanged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.png"
            template = np.zeros((12, 18, 3), dtype=np.uint8)
            template[:, :] = (20, 120, 220)
            cv2.line(template, (2, 2), (15, 9), (250, 250, 250), 2)
            write_image(template_path, template)

            screen = np.zeros((80, 120, 3), dtype=np.uint8)
            screen[10:22, 20:38] = template

            matcher = VisionMatcher()
            calls = []
            original_read_image = __import__("src.vision_matcher", fromlist=["read_image"]).read_image

            def counted_read_image(*args, **kwargs):
                calls.append(args[0])
                return original_read_image(*args, **kwargs)

            with patch("src.vision_matcher.read_image", side_effect=counted_read_image):
                self.assertIsNotNone(matcher.match_template(screen, template_path, threshold=0.99))
                self.assertIsNotNone(matcher.match_template(screen, template_path, threshold=0.99))

        self.assertEqual(calls, [template_path])

    def test_template_cache_invalidates_when_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.png"
            first = np.zeros((12, 18, 3), dtype=np.uint8)
            first[:, :] = (20, 120, 220)
            cv2.line(first, (2, 2), (15, 9), (250, 250, 250), 2)
            write_image(template_path, first)

            screen = np.zeros((80, 120, 3), dtype=np.uint8)
            screen[10:22, 20:38] = first

            matcher = VisionMatcher()
            calls = []
            original_read_image = __import__("src.vision_matcher", fromlist=["read_image"]).read_image

            def counted_read_image(*args, **kwargs):
                calls.append(args[0])
                return original_read_image(*args, **kwargs)

            with patch("src.vision_matcher.read_image", side_effect=counted_read_image):
                self.assertIsNotNone(matcher.match_template(screen, template_path, threshold=0.99))
                second = np.zeros((14, 20, 3), dtype=np.uint8)
                second[:, :] = (90, 40, 180)
                cv2.circle(second, (10, 7), 5, (255, 255, 255), -1)
                write_image(template_path, second)
                screen2 = np.zeros((80, 120, 3), dtype=np.uint8)
                screen2[30:44, 60:80] = second
                self.assertIsNotNone(matcher.match_template(screen2, template_path, threshold=0.99))

        self.assertEqual(calls, [template_path, template_path])

    def test_alpha_template_still_matches_after_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "template.png"
            template = np.zeros((20, 24, 4), dtype=np.uint8)
            template[5:15, 7:19, :3] = (50, 160, 230)
            template[8:12, 10:16, :3] = (250, 250, 250)
            template[5:15, 7:19, 3] = 255
            write_image(template_path, template)

            feature = template[5:15, 7:19, :3]
            screen = np.zeros((70, 90, 3), dtype=np.uint8)
            screen[30:40, 42:54] = feature

            matcher = VisionMatcher()
            first = matcher.match_template(screen, template_path, threshold=0.99)
            second = matcher.match_template(screen, template_path, threshold=0.99)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.center, (48, 35))
        self.assertEqual(second.center, (48, 35))


if __name__ == "__main__":
    unittest.main()
