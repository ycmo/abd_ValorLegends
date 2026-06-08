from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from src.exceptions import TaskSkippedError
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


class FakeArenaReturnController:
    def __init__(self):
        self.taps = []

    def screenshot(self):
        return object()

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeArenaReturnTask(ArenaTask):
    def __init__(self):
        self.context = SimpleNamespace(
            controller=FakeArenaReturnController(),
            navigator=SimpleNamespace(go_to_daily_tasks=lambda max_steps=3: True),
        )
        self.daily_checks = [False, True]
        self.tapped_assets = []

    def _is_daily_tasks_visible(self):
        if self.daily_checks:
            return self.daily_checks.pop(0)
        return True

    def _match_task_asset(self, asset_name, **kwargs):
        if asset_name == "arena_main_anchor.png":
            return object()
        return None

    def _tap_task_asset(self, label, asset_name, **kwargs):
        self.tapped_assets.append((label, asset_name))
        return object()


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

    def test_arena_accepts_low_confidence_very_low_power(self):
        task = ArenaTask(context=object())
        task._get_ocr_reader = lambda: object()
        opponents = [
            {"row": 1, "col": 1, "power_text": "8659k", "power_k": 8659, "confidence": 0.99},
            {"row": 1, "col": 2, "power_text": "8777k", "power_k": 8777, "confidence": 0.99},
            {"row": 2, "col": 1, "power_text": "11769k", "power_k": 11769, "confidence": 0.99},
            {"row": 2, "col": 2, "power_text": "7773k", "power_k": 7773, "confidence": 0.72},
            {"row": 3, "col": 1, "power_text": "252k", "power_k": 252, "confidence": 0.6005},
            {"row": 3, "col": 2, "power_text": "2032k", "power_k": 2032, "confidence": 0.99},
            {"row": 4, "col": 1, "power_text": "3102k", "power_k": 3102, "confidence": 0.76},
            {"row": 4, "col": 2, "power_text": "6872k", "power_k": 6872, "confidence": 0.99},
        ]

        with patch("src.tasks.arena.extract_arena_powers_easyocr", return_value=opponents):
            result = task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertEqual(result[4]["power_text"], "252k")

    def test_arena_accepts_low_confidence_overpowered_value_for_unchecking(self):
        task = ArenaTask(context=object())
        task._get_ocr_reader = lambda: object()
        opponents = [
            {"row": row, "col": col, "power_text": "3000k", "power_k": 3000, "confidence": 0.99}
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        opponents[5] = {"row": 3, "col": 2, "power_text": "8130k", "power_k": 8130, "confidence": 0.634}

        with patch("src.tasks.arena.extract_arena_powers_easyocr", return_value=opponents):
            result = task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertEqual(result[5]["power_text"], "8130k")

    def test_arena_uncertain_ocr_saves_path_prints_and_skips(self):
        task = ArenaTask(context=object())
        task._get_ocr_reader = lambda: object()
        task.returned_to_daily = False
        task._return_from_opponent_list_to_daily_tasks = lambda: setattr(task, "returned_to_daily", True)
        opponents = [
            {"row": row, "col": col, "power_text": "3000k", "power_k": 3000, "confidence": 0.99}
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        opponents[0] = {"row": 1, "col": 1, "power_text": "3000k", "power_k": 3000, "confidence": 0.59}

        output = StringIO()
        with (
            patch("src.tasks.arena.extract_arena_powers_easyocr", return_value=opponents),
            patch("src.tasks.arena.write_image", side_effect=lambda path, image: path),
            redirect_stdout(output),
        ):
            with self.assertRaises(TaskSkippedError) as caught:
                task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertTrue(task.returned_to_daily)
        self.assertIn("saved_screenshot=", output.getvalue())
        self.assertIn("saved_screenshot=", str(caught.exception))


class ArenaVisionTests(TestCase):
    def test_uncertain_opponent_list_return_uses_x_then_arena_back_arrow(self):
        task = FakeArenaReturnTask()

        with patch("src.tasks.arena.time.sleep", return_value=None):
            task._return_from_opponent_list_to_daily_tasks()

        self.assertEqual(task.context.controller.taps, [ArenaTask.OPPONENT_LIST_CLOSE_POINT])
        self.assertEqual(task.tapped_assets, [("leave Arena page", "arena_back_button.png")])

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
