import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.vision_matcher import VisionMatcher, write_image


class VisionMatcherTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
