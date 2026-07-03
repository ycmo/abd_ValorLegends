import unittest
import cv2
import numpy as np
import os
import sys
import shutil

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from Screw.screw_bot import ScrewBot

class MockAdbController:
    def __init__(self):
        self.taps = []
    def tap(self, x, y):
        self.taps.append((x, y))
    def screenshot(self):
        return np.zeros((100, 100, 3), dtype=np.uint8)

class TestScrewBot(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        self.templates_dir = os.path.join(self.test_dir, "test_templates")
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir)
            
        self.screw_template = np.zeros((30, 30), dtype=np.uint8)
        cv2.circle(self.screw_template, (15, 15), 10, 255, -1)
        cv2.imwrite(os.path.join(self.templates_dir, "screw_template.png"), self.screw_template)
        
        self.hole_template = np.zeros((30, 30), dtype=np.uint8)
        cv2.circle(self.hole_template, (15, 15), 10, 128, 2)
        cv2.imwrite(os.path.join(self.templates_dir, "hole_template.png"), self.hole_template)
        
        self.bot = ScrewBot(MockAdbController(), templates_dir=self.templates_dir)
        
    def tearDown(self):
        if os.path.exists(self.templates_dir):
            shutil.rmtree(self.templates_dir)

    def test_is_screw_still_there(self):
        old_pos = (50, 50)
        
        # Exact match
        new_screws = [(10, 10), (50, 50), (100, 100)]
        self.assertTrue(self.bot.is_screw_still_there(old_pos, new_screws))
        
        # Match within tolerance (10px)
        new_screws_shifted = [(10, 10), (55, 45), (100, 100)]
        self.assertTrue(self.bot.is_screw_still_there(old_pos, new_screws_shifted, tolerance=15))
        
        # Missing / Moved out of tolerance
        new_screws_gone = [(10, 10), (100, 100), (200, 200)]
        self.assertFalse(self.bot.is_screw_still_there(old_pos, new_screws_gone))

    def test_detect_objects_multi_scale(self):
        test_img = np.zeros((200, 200, 3), dtype=np.uint8)
        
        screw_color = cv2.cvtColor(self.screw_template, cv2.COLOR_GRAY2BGR)
        test_img[35:65, 35:65] = screw_color
        
        screw_resized = cv2.resize(screw_color, (36, 36))
        test_img[132:168, 132:168] = screw_resized
        
        gray = cv2.cvtColor(test_img, cv2.COLOR_BGR2GRAY)
        
        points = self.bot.detect_objects(gray, self.bot.screw_template, threshold=0.9, scales=[1.0, 1.2])
        self.assertEqual(len(points), 2)
        
        points.sort(key=lambda p: p[1])
        self.assertTrue(abs(points[0][0] - 50) <= 2)
        self.assertTrue(abs(points[0][1] - 50) <= 2)
        self.assertTrue(abs(points[1][0] - 150) <= 2)
        self.assertTrue(abs(points[1][1] - 150) <= 2)

if __name__ == '__main__':
    unittest.main()
