from __future__ import annotations

from pathlib import Path
from unittest import TestCase

import cv2

from src.ocr_utils import extract_arena_powers_easyocr
from src.tasks.arena import ArenaTask
from src.vision_matcher import VisionMatcher, read_image


ARENA_DIR = Path("manual_screenshots") / "\u7af6\u6280\u5834"


def _box(left: int, right: int):
    return [[left, 40], [right, 40], [right, 80], [left, 80]]


class FakeArenaReader:
    def __init__(self):
        self.calls = 0
        self.outputs = [
            [(_box(83, 193), "5630k", 0.99), (_box(291, 311), "1", 0.99)],
            [(_box(73, 183), "9733k", 0.86), (_box(277, 319), "1,", 0.99)],
            [(_box(83, 193), "8127k", 0.99), (_box(291, 311), "1", 0.99)],
            [(_box(74, 183), "7531k", 0.99), (_box(277, 319), "1,", 0.99)],
            [(_box(83, 193), "2934k", 0.99), (_box(291, 311), "1", 0.99)],
            [(_box(73, 183), "2730k", 0.99), (_box(277, 319), "1,", 0.99)],
            [(_box(80, 145), "46,5", 0.98), (_box(129, 199), "585", 0.99)],
            [(_box(67, 190), "11,309", 0.99), (_box(277, 319), "1,", 0.99)],
        ]

    def readtext(self, _image, allowlist=None):
        output = self.outputs[self.calls]
        self.calls += 1
        return output


class ArenaOcrTests(TestCase):
    def test_easyocr_arena_power_extraction_filters_score_text(self):
        screen = read_image(ARENA_DIR / "003_\u9078\u64c7\u5c0d\u624b.png", cv2.IMREAD_COLOR)

        powers = extract_arena_powers_easyocr(screen, reader=FakeArenaReader())

        self.assertEqual([item["power_text"] for item in powers[:6]], [
            "5630k",
            "9733k",
            "8127k",
            "7531k",
            "2934k",
            "2730k",
        ])
        self.assertEqual([item["power_k"] for item in powers[:6]], [5630, 9733, 8127, 7531, 2934, 2730])
        self.assertGreaterEqual(powers[1]["confidence"], 0.86)


class ArenaVisionTests(TestCase):
    def test_checkbox_state_on_manual_opponent_list(self):
        screen = read_image(ARENA_DIR / "003_\u9078\u64c7\u5c0d\u624b.png", cv2.IMREAD_COLOR)
        task = ArenaTask(context=object())

        self.assertEqual(task._checkbox_state(screen, 1, 1), "checked")
        self.assertEqual(task._checkbox_state(screen, 1, 2), "unchecked")
        self.assertEqual(task._checkbox_state(screen, 2, 1), "unchecked")
        self.assertEqual(task._checkbox_state(screen, 3, 2), "checked")

    def test_arena_templates_match_manual_screenshots(self):
        matcher = VisionMatcher()
        cases = [
            ("002_\u9078\u64c7\u6311\u6230.png", "arena_main_anchor.png", ArenaTask.ARENA_MAIN_ROI),
            ("002_\u9078\u64c7\u6311\u6230.png", "multi_challenge_button.png", ArenaTask.MULTI_CHALLENGE_ROI),
            ("003_\u9078\u64c7\u5c0d\u624b.png", "opponent_list_anchor.png", ArenaTask.OPPONENT_LIST_ROI),
            ("003_\u9078\u64c7\u5c0d\u624b.png", "challenge_button.png", ArenaTask.ACTION_BUTTON_ROI),
            ("004_\u9ede\u64ca\u7e7c\u7e8c.png", "continue_button.png", ArenaTask.CONTINUE_BUTTON_ROI),
            ("005_\u9000\u51fa\u7af6\u6280\u5834.png", "arena_back_button.png", ArenaTask.BACK_BUTTON_ROI),
        ]

        for screenshot_name, asset_name, roi in cases:
            with self.subTest(asset=asset_name):
                screen = read_image(ARENA_DIR / screenshot_name, cv2.IMREAD_COLOR)
                match = matcher.match_template(
                    screen,
                    Path("assets/tasks/arena") / asset_name,
                    threshold=0.95,
                    roi=roi,
                )
                self.assertIsNotNone(match)
