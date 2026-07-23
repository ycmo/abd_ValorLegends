from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from src.exceptions import TaskFailedError, TaskSkippedError
from src.ocr_utils import (
    ARENA_POWER_OCR_GAP,
    ARENA_POWER_OCR_PAD,
    ARENA_POWER_OCR_SCALE,
    ARENA_POWER_COL_X_RANGES,
    ARENA_POWER_ROW_Y_RANGES,
    extract_arena_powers_easyocr,
    extract_arena_powers_easyocr_batch,
)
from src.tasks.arena import ArenaSettings, ArenaTask, load_arena_settings, set_arena_mode_override
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


def _arena_batch_box(row: int, col: int, left: int, right: int, top: int = 42, bottom: int = 78):
    cell_w = (ARENA_POWER_COL_X_RANGES[0][1] - ARENA_POWER_COL_X_RANGES[0][0]) * ARENA_POWER_OCR_SCALE + ARENA_POWER_OCR_PAD * 2
    cell_h = (ARENA_POWER_ROW_Y_RANGES[0][1] - ARENA_POWER_ROW_Y_RANGES[0][0]) * ARENA_POWER_OCR_SCALE + ARENA_POWER_OCR_PAD * 2
    slot_left = (col - 1) * (cell_w + ARENA_POWER_OCR_GAP)
    slot_top = (row - 1) * (cell_h + ARENA_POWER_OCR_GAP)
    return [
        [slot_left + left, slot_top + top],
        [slot_left + right, slot_top + top],
        [slot_left + right, slot_top + bottom],
        [slot_left + left, slot_top + bottom],
    ]


class FakeArenaBatchReader:
    def __init__(self):
        self.calls = 0

    def readtext(self, _image, detail=1, allowlist=None):
        self.calls += 1
        powers = [
            ((1, 1), "5630k", 1.0),
            ((1, 2), "9733k", 0.86),
            ((2, 1), "8127k", 1.0),
            ((2, 2), "7531k", 1.0),
            ((3, 1), "2934k", 1.0),
            ((3, 2), "2730k", 0.82),
            ((4, 1), "46,585", 1.0),
            ((4, 2), "11,309", 1.0),
        ]
        results = []
        for (row, col), text, confidence in powers:
            results.append((_arena_batch_box(row, col, 75, 190), text, confidence))
            results.append((_arena_batch_box(row, col, 214, 220), "1,", 1.0))
        return results


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

    def test_batch_easyocr_arena_power_extraction_filters_score_text(self):
        screen = read_image(ARENA_DIR / "003_\u9078\u64c7\u5c0d\u624b.png", cv2.IMREAD_COLOR)
        reader = FakeArenaBatchReader()

        powers = extract_arena_powers_easyocr_batch(screen, reader=reader)

        self.assertEqual(reader.calls, 1)
        self.assertEqual(
            [item["power_text"] for item in powers],
            ["5630k", "9733k", "8127k", "7531k", "2934k", "2730k", "46,585", "11,309"],
        )

    def test_arena_accepts_low_confidence_very_low_power(self):
        task = ArenaTask(context=SimpleNamespace())
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

        with patch("src.tasks.arena.extract_arena_powers_easyocr_batch", return_value=opponents):
            result = task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertEqual(result[4]["power_text"], "252k")

    def test_arena_accepts_low_confidence_overpowered_value_for_unchecking(self):
        task = ArenaTask(context=SimpleNamespace())
        task._get_ocr_reader = lambda: object()
        opponents = [
            {"row": row, "col": col, "power_text": "3000k", "power_k": 3000, "confidence": 0.99}
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        opponents[5] = {"row": 3, "col": 2, "power_text": "8130k", "power_k": 8130, "confidence": 0.634}

        with patch("src.tasks.arena.extract_arena_powers_easyocr_batch", return_value=opponents):
            result = task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertEqual(result[5]["power_text"], "8130k")

    def test_arena_accepts_low_confidence_unscaled_power_without_k_or_m_suffix(self):
        task = ArenaTask(context=SimpleNamespace())
        opponents = [
            {"row": row, "col": col, "power_text": "3000k", "power_k": 3000, "confidence": 0.99, "has_scale_suffix": True}
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        opponents[7] = {
            "row": 4,
            "col": 2,
            "power_text": "47,7784",
            "power_k": 477,
            "confidence": 0.473,
            "has_scale_suffix": False,
        }

        with patch("src.tasks.arena.extract_arena_powers_easyocr_batch", return_value=opponents):
            result = task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertEqual(result[7]["power_text"], "47,7784")

    def test_arena_still_rejects_low_confidence_scaled_mid_power(self):
        task = ArenaTask(context=SimpleNamespace())
        task._get_ocr_reader = lambda: object()
        task._return_from_opponent_list_to_daily_tasks = lambda: None
        opponents = [
            {"row": row, "col": col, "power_text": "3000k", "power_k": 3000, "confidence": 0.99, "has_scale_suffix": True}
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        opponents[0] = {"row": 1, "col": 1, "power_text": "3000k", "power_k": 3000, "confidence": 0.40, "has_scale_suffix": True}

        with (
            patch("src.tasks.arena.extract_arena_powers_easyocr_batch", return_value=opponents),
            patch("src.tasks.arena.extract_arena_powers_easyocr", return_value=opponents),
            patch("src.tasks.arena.write_image", side_effect=lambda path, image: path),
        ):
            with self.assertRaises(TaskSkippedError):
                task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

    def test_arena_uncertain_ocr_saves_path_prints_and_skips(self):
        task = ArenaTask(context=SimpleNamespace())
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
            patch("src.tasks.arena.extract_arena_powers_easyocr_batch", return_value=opponents),
            patch("src.tasks.arena.extract_arena_powers_easyocr", return_value=opponents),
            patch("src.tasks.arena.write_image", side_effect=lambda path, image: path),
            redirect_stdout(output),
        ):
            with self.assertRaises(TaskSkippedError) as caught:
                task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertTrue(task.returned_to_daily)
        self.assertIn("saved_screenshot=", output.getvalue())
        self.assertIn("saved_screenshot=", str(caught.exception))

    def test_arena_falls_back_to_per_slot_ocr_when_batch_is_uncertain(self):
        task = ArenaTask(context=SimpleNamespace())
        task._get_ocr_reader = lambda: object()
        batch_opponents = [
            {"row": row, "col": col, "power_text": "", "power_k": -1, "confidence": 0.0, "has_scale_suffix": False}
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        fallback_opponents = [
            {"row": row, "col": col, "power_text": "3000k", "power_k": 3000, "confidence": 0.99, "has_scale_suffix": True}
            for row in range(1, 5)
            for col in range(1, 3)
        ]

        with (
            patch("src.tasks.arena.extract_arena_powers_easyocr_batch", return_value=batch_opponents) as batch,
            patch("src.tasks.arena.extract_arena_powers_easyocr", return_value=fallback_opponents) as fallback,
        ):
            result = task._read_opponents(np.zeros((540, 960, 3), dtype=np.uint8))

        self.assertEqual(result, fallback_opponents)
        batch.assert_called_once()
        fallback.assert_called_once()


class ArenaVisionTests(TestCase):
    def test_uncertain_opponent_list_return_uses_x_then_arena_back_arrow(self):
        task = FakeArenaReturnTask()

        with patch("src.tasks.arena.time.sleep", return_value=None):
            task._return_from_opponent_list_to_daily_tasks()

        self.assertEqual(task.context.controller.taps, [ArenaTask.OPPONENT_LIST_CLOSE_POINT])
        self.assertEqual(task.tapped_assets, [("leave Arena page", "arena_back_button.png")])

    def test_checkbox_state_on_manual_opponent_list(self):
        screen = read_image(ARENA_DIR / "003_\u9078\u64c7\u5c0d\u624b.png", cv2.IMREAD_COLOR)
        task = ArenaTask(context=SimpleNamespace())

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
            ("003_\u9078\u64c7\u5c0d\u624b.png", "refresh_button.png", ArenaTask.REFRESH_BUTTON_ROI),
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

    def test_arena_ticket_count_reads_manual_screenshot(self):
        class Reader:
            def readtext(self, _image, detail=1, allowlist=None):
                return [([[20, 10], [80, 10], [80, 40], [20, 40]], "148", 0.99)]

        task = ArenaTask(context=SimpleNamespace())
        task._get_ocr_reader = lambda: Reader()
        screen = read_image(ARENA_DIR / "005_\u9000\u51fa\u7af6\u6280\u5834.png", cv2.IMREAD_COLOR)

        value, confidence, detail = task._read_ticket_count(screen)

        self.assertEqual(value, 148)
        self.assertEqual(confidence, 0.99)
        self.assertIn("ocr_source=fast_accept", detail)

    def test_tickets_20_mode_stops_when_ticket_floor_reached(self):
        task = ArenaTask(context=SimpleNamespace())
        task.settings = ArenaSettings(mode="tickets_20", target_fights=None, ticket_floor=20)
        task._ticket_count_at_or_below_floor = lambda: True

        self.assertFalse(task._should_continue(total_fought=0))

    def test_ticket_count_check_retries_transient_ocr_failure(self):
        class Controller:
            def screenshot(self):
                return object()

        class Matcher:
            def match_template(self, *_args, **_kwargs):
                return object()

        task = ArenaTask(context=SimpleNamespace(controller=Controller(), matcher=Matcher()))
        task.settings = ArenaSettings(mode="tickets_20", ticket_floor=20)
        task.TICKET_OCR_RETRY_SECONDS = 0
        reads = [(None, 0.0), (19, 0.99)]
        task._read_ticket_count = lambda _screen: reads.pop(0)

        self.assertTrue(task._ticket_count_at_or_below_floor())

    def test_ticket_count_check_rejects_low_confidence_even_when_clearly_above_floor(self):
        class Controller:
            def screenshot(self):
                return object()

        class Matcher:
            def match_template(self, *_args, **_kwargs):
                return object()

        task = ArenaTask(context=SimpleNamespace(controller=Controller(), matcher=Matcher()))
        task.settings = ArenaSettings(mode="tickets_20", ticket_floor=20)
        task.TICKET_OCR_ATTEMPTS = 1
        task.TICKET_OCR_RETRY_SECONDS = 0
        task._read_ticket_count = lambda _screen: (453, 0.525)
        task._save_ticket_ocr_uncertain_debug = lambda _screen, _confidence: "ticket_debug.png"

        with self.assertRaises(TaskFailedError):
            task._ticket_count_at_or_below_floor()

    def test_ticket_count_check_retries_low_confidence_near_floor(self):
        class Controller:
            def screenshot(self):
                return object()

        class Matcher:
            def match_template(self, *_args, **_kwargs):
                return object()

        task = ArenaTask(context=SimpleNamespace(controller=Controller(), matcher=Matcher()))
        task.settings = ArenaSettings(mode="tickets_20", ticket_floor=20)
        task.TICKET_OCR_ATTEMPTS = 1
        task.TICKET_OCR_RETRY_SECONDS = 0
        task._read_ticket_count = lambda _screen: (19, 0.525)
        task._save_ticket_ocr_uncertain_debug = lambda _screen, _confidence: "ticket_debug.png"

        with self.assertRaises(TaskFailedError):
            task._ticket_count_at_or_below_floor()

    def test_ticket_count_check_reports_saved_screenshot_after_retries_fail(self):
        class Controller:
            def screenshot(self):
                return object()

        class Matcher:
            def match_template(self, *_args, **_kwargs):
                return object()

        task = ArenaTask(context=SimpleNamespace(controller=Controller(), matcher=Matcher()))
        task.settings = ArenaSettings(mode="tickets_20", ticket_floor=20)
        task.TICKET_OCR_ATTEMPTS = 2
        task.TICKET_OCR_RETRY_SECONDS = 0
        task._read_ticket_count = lambda _screen: (None, 0.1)
        task._save_ticket_ocr_uncertain_debug = lambda _screen, _confidence: "ticket_debug.png"

        with self.assertRaises(TaskFailedError) as caught:
            task._ticket_count_at_or_below_floor()

        self.assertIn("saved_screenshot=ticket_debug.png", str(caught.exception))

    def test_no_safe_opponents_refreshes_when_enabled(self):
        task = ArenaTask(context=SimpleNamespace())
        task.settings = ArenaSettings(
            mode="daily",
            max_power_k=6500,
            target_fights=8,
            ticket_floor=None,
            refresh_on_no_safe_opponents=True,
            max_refreshes=2,
        )
        task._require_opponent_list_screen = lambda: "screen"
        task._read_opponents = lambda _screen: [
            {"row": row, "col": col, "power_text": "9000k", "power_k": 9000, "confidence": 0.99}
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        task._checkbox_state = lambda _screen, _row, _col: "unchecked"
        task._count_checked_opponents = lambda _screen: 0
        task.refreshed = False
        task._refresh_opponent_list = lambda: setattr(task, "refreshed", True)

        result = task._uncheck_overpowered_and_start(refreshes=0)

        self.assertEqual(result, 0)
        self.assertTrue(task.refreshed)

    def test_cached_checked_opponents_skip_only_cached_positions(self):
        task = ArenaTask(context=SimpleNamespace())
        task._cached_selected_opponents = [(1, 1), (3, 2)]
        task._require_opponent_list_screen = lambda: "screen"
        task._checkbox_state = lambda _screen, row, col: (
            "checked" if (row, col) in task._cached_selected_opponents else "unchecked"
        )
        task._read_opponents = lambda _screen: [
            {"row": 1, "col": 1, "power_text": "9000k", "power_k": 9000, "confidence": 0.99},
            {"row": 2, "col": 1, "power_text": "9100k", "power_k": 9100, "confidence": 0.99},
            {"row": 3, "col": 2, "power_text": "9200k", "power_k": 9200, "confidence": 0.99},
        ]
        task.started = []
        task._tap_task_asset = lambda *args, **kwargs: task.started.append((args, kwargs))

        result = task._uncheck_overpowered_and_start(refreshes=0)

        self.assertEqual(result, 2)
        self.assertEqual(len(task.started), 1)
        self.assertEqual(task._cached_selected_opponents, [(1, 1), (3, 2)])

    def test_full_cached_checked_page_starts_without_ocr(self):
        task = ArenaTask(context=SimpleNamespace())
        task._cached_selected_opponents = [
            (row, col)
            for row in range(1, 5)
            for col in range(1, 3)
        ]
        task._require_opponent_list_screen = lambda: "screen"
        task._read_opponents = lambda _screen: self.fail("full cached page should skip opponent OCR")
        task._checkbox_state = lambda _screen, _row, _col: self.fail("full cached page should skip checkbox checks")
        task.started = []
        task._tap_task_asset = lambda *args, **kwargs: task.started.append((args, kwargs))

        result = task._uncheck_overpowered_and_start(refreshes=0)

        self.assertEqual(result, 8)
        self.assertEqual(len(task.started), 1)

    def test_cached_checked_opponents_falls_back_when_cache_is_stale(self):
        task = ArenaTask(context=SimpleNamespace())
        task.settings = ArenaSettings(max_power_k=6500)
        task._cached_selected_opponents = [(1, 1)]
        task._require_opponent_list_screen = lambda: "screen"
        task._read_opponents_called = False
        task._read_opponents = lambda _screen: setattr(task, "_read_opponents_called", True) or []
        task._checked_opponent_positions = lambda _screen: [(2, 1)]
        task._checkbox_state = lambda _screen, _row, _col: "unchecked"
        task._tap_task_asset = lambda *args, **kwargs: None

        result = task._uncheck_overpowered_and_start(refreshes=0)

        self.assertEqual(result, 1)
        self.assertTrue(task._read_opponents_called)
        self.assertEqual(task._cached_selected_opponents, [(2, 1)])

    def test_ticket_mode_unchecks_overpowered_opponents_before_refresh(self):
        class Controller:
            def __init__(self):
                self.taps = []

            def tap(self, x, y):
                self.taps.append((x, y))

        task = ArenaTask(context=SimpleNamespace(controller=Controller()))
        task.settings = ArenaSettings(
            mode="tickets_20",
            max_power_k=6500,
            target_fights=None,
            ticket_floor=20,
            refresh_on_no_safe_opponents=True,
            max_refreshes=2,
        )
        screens = ["screen1", "screen2", "screen3"]
        task._require_opponent_list_screen = lambda: screens.pop(0) if screens else "screen_after_uncheck"
        task._read_opponents = lambda _screen: [
            {"row": 1, "col": 1, "power_text": "9000k", "power_k": 9000, "confidence": 0.99},
            {"row": 1, "col": 2, "power_text": "9100k", "power_k": 9100, "confidence": 0.99},
        ]
        checked = {(1, 1), (1, 2)}

        def checkbox_state(_screen, row, col):
            return "checked" if (row, col) in checked else "unchecked"

        def tap_checkbox(row, col):
            checked.discard((row, col))
            return (row, col)

        task._checkbox_state = checkbox_state
        task._checkbox_center = tap_checkbox
        task._count_checked_opponents = lambda _screen: len(checked)
        task.events = []
        task._refresh_opponent_list = lambda: task.events.append(("refresh", tuple(task.context.controller.taps)))

        result = task._uncheck_overpowered_and_start(refreshes=0)

        self.assertEqual(result, 0)
        self.assertEqual(task.context.controller.taps, [(1, 1), (1, 2)])
        self.assertEqual(task.events, [("refresh", ((1, 1), (1, 2)))])


class ArenaConfigTests(TestCase):
    def tearDown(self):
        set_arena_mode_override(None)

    def test_load_arena_settings_supports_jsonc_modes_and_account_override(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "current_account.json"
            state.write_text('{"account": "311"}', encoding="utf-8")
            config = root / "arena.jsonc"
            config.write_text(
                """
                {
                  "mode": "tickets_20",
                  "active_account_file": "current_account.json",
                  "refresh_on_no_safe_opponents": true,
                  "max_refreshes": 9,
                  "modes": {
                    "tickets_20": {
                      "target_fights": null,
                      "ticket_floor": 20,
                      "max_rounds": 33
                    }
                  },
                  "accounts": {
                    "default": {"max_power_k": 6500},
                    "311": {"max_power_k": 7200}
                  }
                }
                """,
                encoding="utf-8",
            )
            with patch("src.tasks.arena.ROOT_DIR", root):
                settings = load_arena_settings(config)

        self.assertEqual(settings.mode, "tickets_20")
        self.assertEqual(settings.account, "311")
        self.assertEqual(settings.max_power_k, 7200)
        self.assertIsNone(settings.target_fights)
        self.assertEqual(settings.ticket_floor, 20)
        self.assertTrue(settings.refresh_on_no_safe_opponents)
        self.assertEqual(settings.max_refreshes, 9)
        self.assertEqual(settings.max_rounds, 33)

    def test_arena_mode_override_wins_over_config_mode(self):
        with TemporaryDirectory() as tmp:
            config = Path(tmp) / "arena.jsonc"
            config.write_text(
                """
                {
                  "mode": "daily",
                  "modes": {
                    "daily": {"target_fights": 8, "ticket_floor": null},
                    "tickets_20": {"target_fights": null, "ticket_floor": 20}
                  },
                  "accounts": {"default": {"max_power_k": 6500}}
                }
                """,
                encoding="utf-8",
            )
            set_arena_mode_override("tickets_20")

            settings = load_arena_settings(config)

        self.assertEqual(settings.mode, "tickets_20")
        self.assertIsNone(settings.target_fights)
        self.assertEqual(settings.ticket_floor, 20)
