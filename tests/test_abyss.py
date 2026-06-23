from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.main import _format_abyss_rental_row
from src.tasks.abyss import AbyssTask
from src.vision_matcher import MatchResult


class FakeMatcher:
    def __init__(self, matches, rented_matches=None):
        self.matches = matches
        self.rented_matches = rented_matches or []

    def match_template_all(self, _screen, path, **_kwargs):
        if Path(path).name == "rented_button.png":
            return self.rented_matches
        return self.matches

    def match_template(self, *_args, **_kwargs):
        return None

    def best_template_match(self, *_args, **_kwargs):
        return None


class QueueMatcher(FakeMatcher):
    def __init__(self, matches):
        super().__init__([])
        self.template_matches = list(matches)

    def match_template(self, *_args, **_kwargs):
        if not self.template_matches:
            return None
        return self.template_matches.pop(0)


class ScriptedTemplateMatcher(FakeMatcher):
    def __init__(self, script):
        super().__init__([])
        self.script = list(script)

    def match_template(self, _screen, path, **_kwargs):
        if not self.script:
            return None
        expected_name, match = self.script.pop(0)
        self.assert_name(expected_name, Path(path).name)
        return match

    @staticmethod
    def assert_name(expected, actual):
        if expected != actual:
            raise AssertionError(f"expected template {expected}, got {actual}")


class FakeController:
    def __init__(self):
        self.swipes = []
        self.taps = []
        self.debug_saves = []

    def screenshot(self):
        return np.zeros((540, 960, 3), dtype=np.uint8)

    def save_annotated_debug(self, *args, **kwargs):
        self.debug_saves.append((args, kwargs))
        return None

    def annotate_next_tap_debug(self, **_kwargs):
        pass

    def tap(self, *args):
        self.taps.append(args)

    def swipe(self, *args, **kwargs):
        self.swipes.append((args, kwargs))


class AbyssTaskTests(unittest.TestCase):
    def test_execute_skips_when_main_done_zero_is_visible(self):
        controller = FakeController()
        done = MatchResult(Path("main_done_zero.png"), 0.99, (924, 456), (908, 441, 33, 30))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher([("main_done_zero.png", done)]),
            logger=None,
        )
        task = AbyssTask(context)

        result = task.run()

        self.assertEqual(result.state.value, "skipped")
        self.assertIn("main_done_zero.png", result.message)
        self.assertEqual(controller.taps, [])

    def test_scan_rental_view_crops_only_rows_with_available_rent_buttons(self):
        matches = [
            MatchResult(Path("rent_button.png"), 0.98, (747, 165), (690, 150, 60, 24)),
            MatchResult(Path("rent_button.png"), 0.96, (747, 361), (690, 346, 60, 24)),
        ]
        context = SimpleNamespace(
            controller=FakeController(),
            matcher=FakeMatcher(matches),
            logger=None,
        )
        task = AbyssTask(context)
        task._is_dragon_rental_row = lambda _screen, _row_y: True

        def fake_read_power(_screen, _roi, _debug_dir, scan_index, row_index):
            return (f"{scan_index}{row_index}00", 0.9, Path(f"{scan_index}_{row_index}.png"))

        task._read_power_ocr = fake_read_power

        rows = task._scan_rental_view(np.zeros((540, 960, 3), dtype=np.uint8), 1, Path("debug"))

        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].rent_available)
        self.assertTrue(rows[1].rent_available)
        self.assertEqual(rows[0].power_text, "1100")

    def test_best_available_rental_ignores_gray_or_unreadable_rows(self):
        context = SimpleNamespace(controller=FakeController(), matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        rows = [
            SimpleNamespace(rent_available=True, power_k=-1, rent_center=(1, 1), confidence=1.0),
            SimpleNamespace(rent_available=False, power_k=9999, rent_center=None, confidence=1.0),
            SimpleNamespace(rent_available=True, power_k=1200, rent_center=(2, 2), confidence=1.0),
            SimpleNamespace(rent_available=True, power_k=1500, rent_center=(3, 3), confidence=1.0),
        ]

        best = task._best_available_rental(rows)

        self.assertEqual(best.power_k, 1500)
        self.assertEqual(best.rent_center, (3, 3))

    def test_best_available_rental_ignores_low_ocr_confidence(self):
        context = SimpleNamespace(controller=FakeController(), matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        rows = [
            SimpleNamespace(rent_available=True, power_k=9999, rent_center=(1, 1), confidence=0.30),
            SimpleNamespace(rent_available=True, power_k=1200, rent_center=(2, 2), confidence=0.95),
        ]

        best = task._best_available_rental(rows)

        self.assertEqual(best.power_k, 1200)

    def test_dim_rent_button_is_not_available(self):
        context = SimpleNamespace(controller=FakeController(), matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        dim_match = MatchResult(
            Path("rent_button.png"),
            0.99,
            (746, 260),
            (690, 248, 60, 24),
            brightness_ratio=0.80,
        )

        self.assertFalse(task._is_active_rent_button(dim_match))

    def test_scan_rental_view_filters_rented_but_keeps_partial_for_ocr_review(self):
        active = MatchResult(Path("rent_button.png"), 0.98, (747, 165), (690, 150, 60, 24))
        rented_low_active = MatchResult(Path("rent_button.png"), 0.87, (747, 260), (690, 248, 60, 24))
        partial = MatchResult(Path("rent_button.png"), 0.84, (747, 455), (690, 443, 60, 24))
        rented = MatchResult(Path("rented_button.png"), 1.0, (747, 260), (690, 248, 60, 24))
        context = SimpleNamespace(
            controller=FakeController(),
            matcher=FakeMatcher([active, rented_low_active, partial], rented_matches=[rented]),
            logger=None,
        )
        task = AbyssTask(context)
        task._is_dragon_rental_row = lambda _screen, _row_y: True
        task._read_power_ocr = lambda _screen, _roi, _debug_dir, scan_index, row_index: (
            f"{scan_index}{row_index}00",
            0.9,
            Path(f"{scan_index}_{row_index}.png"),
        )

        rows = task._scan_rental_view(np.zeros((540, 960, 3), dtype=np.uint8), 1, Path("debug"))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].rent_center, (747, 165))
        self.assertEqual(rows[1].rent_center, (747, 455))

    def test_rental_scan_indicates_already_rented_when_many_rented_and_no_active_buttons(self):
        rented_matches = [
            MatchResult(Path("rented_button.png"), 1.0, (747, y), (690, y - 12, 60, 24))
            for y in (160, 240, 320, 400)
        ]
        context = SimpleNamespace(
            controller=FakeController(),
            matcher=FakeMatcher([], rented_matches=rented_matches),
            logger=None,
        )
        task = AbyssTask(context)
        task._is_dragon_rental_row = lambda _screen, _row_y: True
        task._last_rental_scan_active_count = 0
        task._last_rental_scan_rented_count = 0
        task._read_power_ocr = lambda *_args: ("", 0.0, Path("unused.png"))

        rows = task._scan_rental_view(np.zeros((540, 960, 3), dtype=np.uint8), 1, Path("debug"))

        self.assertEqual(rows, [])
        self.assertTrue(task._rental_scan_indicates_already_rented())

    def test_scan_rental_view_filters_non_dragon_rows(self):
        matches = [
            MatchResult(Path("rent_button.png"), 0.98, (747, 165), (690, 150, 60, 24)),
            MatchResult(Path("rent_button.png"), 0.96, (747, 361), (690, 346, 60, 24)),
        ]
        context = SimpleNamespace(
            controller=FakeController(),
            matcher=FakeMatcher(matches),
            logger=None,
        )
        task = AbyssTask(context)
        task._is_dragon_rental_row = lambda _screen, row_y: row_y < 200
        task._read_power_ocr = lambda _screen, _roi, _debug_dir, scan_index, row_index: (
            f"{scan_index}{row_index}00",
            0.9,
            Path(f"{scan_index}_{row_index}.png"),
        )

        rows = task._scan_rental_view(np.zeros((540, 960, 3), dtype=np.uint8), 1, Path("debug"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rent_center, (747, 165))

    def test_rental_scan_indicates_no_dragon_candidate_when_active_buttons_exist(self):
        matches = [
            MatchResult(Path("rent_button.png"), 0.98, (747, 165), (690, 150, 60, 24)),
            MatchResult(Path("rent_button.png"), 0.96, (747, 361), (690, 346, 60, 24)),
        ]
        context = SimpleNamespace(
            controller=FakeController(),
            matcher=FakeMatcher(matches),
            logger=None,
        )
        task = AbyssTask(context)
        task._is_dragon_rental_row = lambda _screen, _row_y: False

        rows = task._scan_rental_view(np.zeros((540, 960, 3), dtype=np.uint8), 1, Path("debug"))

        self.assertEqual(rows, [])
        self.assertTrue(task._rental_scan_indicates_no_dragon_candidate())

    def test_execute_message_handles_skipped_rental(self):
        context = SimpleNamespace(controller=FakeController(), matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        task._tap_rental_entry = lambda: None
        task.probe_rental_scan = lambda tap_forest=True: []
        task._rental_scan_indicates_already_rented = lambda: True
        task._tap_training_entry = lambda: None
        task._tap_rented_hero = lambda: None
        task._ensure_artifact_plan_2 = lambda: None
        task._tap_start_training = lambda: None
        task._wait_skip_and_keep_result = lambda: None

        with patch("src.tasks.abyss.time.sleep"):
            message = task.execute()

        self.assertEqual(message, "abyss one round completed; rental skipped: already rented")
        self.assertEqual(context.controller.taps, [])

    def test_execute_message_handles_no_dragon_rental_candidate(self):
        context = SimpleNamespace(controller=FakeController(), matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        task._tap_rental_entry = lambda: None
        task.probe_rental_scan = lambda tap_forest=True: []
        task._rental_scan_indicates_already_rented = lambda: False
        task._rental_scan_indicates_no_dragon_candidate = lambda: True
        task._tap_training_entry = lambda: None
        task._tap_rented_hero = lambda: None
        task._ensure_artifact_plan_2 = lambda: None
        task._tap_start_training = lambda: None
        task._wait_skip_and_keep_result = lambda: None

        with patch("src.tasks.abyss.time.sleep"):
            message = task.execute()

        self.assertEqual(message, "abyss one round completed; rental skipped: no dragon candidate")
        self.assertEqual(context.controller.taps, [])

    def test_tap_rental_entry_waits_for_entry_template_then_rental_view(self):
        controller = FakeController()
        entry = MatchResult(Path("rental_entry_button.png"), 0.96, (782, 491), (750, 455, 78, 76))
        forest = MatchResult(Path("forest_tab.png"), 0.91, (507, 466), (470, 437, 74, 59))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher(
                [
                    ("rental_entry_button.png", None),
                    ("rental_entry_button.png", entry),
                    ("forest_tab.png", forest),
                ]
            ),
            logger=None,
        )
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._tap_rental_entry()

        self.assertEqual(controller.taps, [(782, 491)])

    def test_tap_training_entry_uses_template_center_and_waits_for_formation(self):
        controller = FakeController()
        training = MatchResult(Path("training_button.png"), 0.95, (910, 290), (885, 260, 50, 70))
        start = MatchResult(Path("start_training_button.png"), 0.94, (885, 470), (830, 435, 110, 60))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher(
                [
                    ("busy_waiting_overlay.png", None),
                    ("training_button.png", training),
                    ("busy_waiting_overlay.png", None),
                    ("start_training_button.png", start),
                ]
            ),
            logger=None,
        )
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._tap_training_entry()

        self.assertEqual(controller.taps, [(910, 290)])

    def test_rented_hero_selection_waits_for_formation_and_confirms_checkmark(self):
        controller = FakeController()
        start = MatchResult(Path("start_training_button.png"), 0.99, (900, 480), (860, 450, 80, 60))
        available = MatchResult(Path("rented_hero_available.png"), 1.0, (57, 481), (29, 466, 57, 31))
        selected = MatchResult(Path("rented_hero_selected.png"), 1.0, (56, 482), (26, 465, 60, 33))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher(
                [
                    ("artifact_tab_2.png", None),
                    ("busy_waiting_overlay.png", None),
                    ("start_training_button.png", start),
                    ("rented_hero_selected.png", None),
                    ("rented_hero_available.png", available),
                    ("rented_hero_selected.png", selected),
                ]
            ),
            logger=None,
        )
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._tap_rented_hero()

        self.assertEqual(controller.taps, [(55, 482)])

    def test_rented_hero_selection_skips_when_first_slot_is_not_rented_hero(self):
        controller = FakeController()
        start = MatchResult(Path("start_training_button.png"), 0.99, (900, 480), (860, 450, 80, 60))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher(
                [
                    ("artifact_tab_2.png", None),
                    ("busy_waiting_overlay.png", None),
                    ("start_training_button.png", start),
                    ("rented_hero_selected.png", None),
                    ("rented_hero_available.png", None),
                ]
            ),
            logger=None,
        )
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._tap_rented_hero()

        self.assertEqual(controller.taps, [])
        self.assertEqual(controller.debug_saves[0][0][0], "abyss_rented_hero_not_available")

    def test_rented_hero_selection_closes_artifact_dialog_first(self):
        controller = FakeController()
        artifact_tab = MatchResult(Path("artifact_tab_2.png"), 1.0, (622, 115), (600, 100, 44, 30))
        start = MatchResult(Path("start_training_button.png"), 0.99, (900, 480), (860, 450, 80, 60))
        selected = MatchResult(Path("rented_hero_selected.png"), 1.0, (56, 482), (26, 465, 60, 33))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher(
                [
                    ("artifact_tab_2.png", artifact_tab),
                    ("busy_waiting_overlay.png", None),
                    ("start_training_button.png", start),
                    ("rented_hero_selected.png", selected),
                ]
            ),
            logger=None,
        )
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._tap_rented_hero()

        self.assertEqual(controller.taps, [(850, 95)])

    def test_rental_list_swipe_stays_inside_power_column_roi(self):
        controller = FakeController()
        context = SimpleNamespace(controller=controller, matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._swipe_rental_list()

        self.assertEqual(controller.swipes, [((455, 430, 455, 170), {"duration_ms": 520})])

    def test_artifact_plan_missing_error_names_template_files(self):
        context = SimpleNamespace(controller=FakeController(), matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)

        with self.assertRaisesRegex(
            Exception,
            "artifact_plan_2.png, artifact_plan_1.png",
        ):
            task._ensure_artifact_plan_2()

    def test_artifact_plan_already_2_saves_recognition_debug(self):
        controller = FakeController()
        plan_2 = MatchResult(Path("artifact_plan_2.png"), 0.93, (914, 286), (890, 260, 48, 52))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher([
                ("artifact_plan_2.png", plan_2),
                ("artifact_plan_1.png", None),
            ]),
            logger=None,
        )
        task = AbyssTask(context)

        task._ensure_artifact_plan_2()

        self.assertEqual(len(controller.debug_saves), 1)
        args, kwargs = controller.debug_saves[0]
        self.assertEqual(args[0], "abyss_artifact_plan_already_2")
        self.assertIn("artifact_plan_2.png", "\n".join(kwargs["lines"]))

    def test_artifact_plan_1_beats_false_positive_plan_2(self):
        controller = FakeController()
        plan_2 = MatchResult(Path("artifact_plan_2.png"), 0.89, (916, 279), (902, 262, 28, 35))
        plan_1 = MatchResult(Path("artifact_plan_1.png"), 1.00, (915, 275), (898, 257, 34, 36))
        context = SimpleNamespace(
            controller=controller,
            matcher=ScriptedTemplateMatcher([
                ("artifact_plan_2.png", plan_2),
                ("artifact_plan_1.png", plan_1),
            ]),
            logger=None,
        )
        task = AbyssTask(context)
        switched = []
        task._switch_artifact_dialog_to_plan_2 = lambda: switched.append(True)

        with patch("src.tasks.abyss.time.sleep"):
            task._ensure_artifact_plan_2()

        self.assertEqual(controller.taps, [(915, 275)])
        self.assertEqual(switched, [True])

    def test_reverse_search_swipes_until_target_power_is_found(self):
        controller = FakeController()
        context = SimpleNamespace(controller=controller, matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        task._save_rental_probe_summary = lambda *_args: None
        target = SimpleNamespace(scan_index=4, power_text="1,277,713", power_k=1277)
        empty_rows = [
            SimpleNamespace(
                scan_index=5,
                row_index=2,
                rent_available=True,
                rent_center=(746, 260),
                power_text="1,000,000",
                power_k=1000,
                confidence=1.0,
            )
        ]
        target_rows = [
            SimpleNamespace(
                scan_index=4,
                row_index=3,
                rent_available=True,
                rent_center=(746, 358),
                power_text="1,277,713",
                power_k=1277,
                confidence=1.0,
            )
        ]
        scans = [empty_rows, target_rows]
        task._scan_rental_view = lambda *_args: scans.pop(0)

        with patch("src.tasks.abyss.time.sleep"):
            task._find_and_tap_rental_candidate_by_reverse_search(target)

        self.assertEqual(controller.swipes, [((455, 190, 455, 370), {"duration_ms": 520})])
        self.assertEqual(controller.taps, [(746, 358)])

    def test_reverse_search_allows_more_attempts_for_small_reverse_swipes(self):
        controller = FakeController()
        context = SimpleNamespace(controller=controller, matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        task._save_rental_probe_summary = lambda *_args: None
        target = SimpleNamespace(scan_index=2, power_text="1,525,412", power_k=1525)
        empty_rows = [
            [SimpleNamespace(scan_index=index, row_index=1, rent_available=True, rent_center=(746, 260), power_text="1,000,000", power_k=1000, confidence=1.0)]
            for index in range(6)
        ]
        target_rows = [
            SimpleNamespace(
                scan_index=7,
                row_index=1,
                rent_available=True,
                rent_center=(746, 165),
                power_text="1,525,412",
                power_k=1525,
                confidence=1.0,
            )
        ]
        scans = empty_rows + [target_rows]
        task._scan_rental_view = lambda *_args: scans.pop(0)

        with patch("src.tasks.abyss.time.sleep"):
            task._find_and_tap_rental_candidate_by_reverse_search(target)

        self.assertEqual(len(controller.swipes), 6)
        self.assertEqual(controller.taps, [(746, 165)])

    def test_tap_rental_candidate_marks_and_taps_selected_button(self):
        controller = FakeController()
        context = SimpleNamespace(controller=controller, matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)
        row = SimpleNamespace(
            scan_index=2,
            row_index=4,
            power_text="1,277,713",
            confidence=0.95,
            rent_center=(746, 455),
        )

        task._tap_rental_candidate(row)

        self.assertEqual(controller.taps, [(746, 455)])

    def test_post_battle_result_loop_taps_until_final_done_then_exits(self):
        controller = FakeController()
        accept = MatchResult(Path("accept_result_button.png"), 1.0, (368, 478), (338, 466, 60, 24))
        yes = MatchResult(Path("yes_button.png"), 1.0, (590, 398), (568, 380, 44, 37))
        done = MatchResult(Path("final_done_zero.png"), 1.0, (408, 477), (393, 466, 40, 26))
        exit_button = MatchResult(Path("exit_button.png"), 1.0, (590, 477), (564, 460, 53, 35))
        script = [
            ("final_done_zero.png", None),
            ("accept_result_button.png", accept),
            ("final_done_zero.png", None),
            ("accept_result_button.png", None),
            ("yes_button.png", yes),
            ("final_done_zero.png", done),
            ("exit_button.png", exit_button),
        ]
        context = SimpleNamespace(controller=controller, matcher=ScriptedTemplateMatcher(script), logger=None)
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._run_post_battle_result_sequence()

        self.assertEqual(controller.taps, [(368, 478), (590, 398), (590, 477)])

    def test_initial_zero_status_exits_without_tapping_keep_result(self):
        controller = FakeController()
        initial_done = MatchResult(Path("initial_done_zero.png"), 0.98, (438, 443), (418, 435, 40, 17))
        exit_button = MatchResult(Path("exit_button.png"), 1.0, (590, 477), (570, 466, 41, 23))
        script = [
            ("initial_done_zero.png", initial_done),
            ("exit_button.png", exit_button),
            ("exit_button.png", exit_button),
            ("initial_done_zero.png", None),
            ("exit_button.png", None),
        ]
        context = SimpleNamespace(controller=controller, matcher=ScriptedTemplateMatcher(script), logger=None)
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._wait_skip_and_keep_result()

        self.assertEqual(controller.taps, [(590, 477)])

    def test_post_battle_result_loop_uses_long_wait_after_action_buttons(self):
        controller = FakeController()
        yes = MatchResult(Path("yes_button.png"), 1.0, (590, 398), (568, 380, 44, 37))
        done = MatchResult(Path("final_done_zero.png"), 1.0, (408, 477), (393, 466, 40, 26))
        exit_button = MatchResult(Path("exit_button.png"), 1.0, (590, 477), (564, 460, 53, 35))
        script = [
            ("final_done_zero.png", None),
            ("accept_result_button.png", None),
            ("yes_button.png", yes),
            ("final_done_zero.png", done),
            ("exit_button.png", exit_button),
        ]
        context = SimpleNamespace(controller=controller, matcher=ScriptedTemplateMatcher(script), logger=None)
        task = AbyssTask(context)
        sleeps = []

        with patch("src.tasks.abyss.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            task._run_post_battle_result_sequence()

        self.assertEqual(sleeps[0], task.POST_RESULT_WAIT_SECONDS)
        self.assertEqual(controller.taps, [(590, 398), (590, 477)])

    def test_post_battle_result_loop_uses_short_wait_after_accept_result(self):
        controller = FakeController()
        accept = MatchResult(Path("accept_result_button.png"), 1.0, (368, 478), (338, 466, 60, 24))
        yes = MatchResult(Path("yes_button.png"), 1.0, (590, 398), (568, 380, 44, 37))
        done = MatchResult(Path("final_done_zero.png"), 1.0, (408, 477), (393, 466, 40, 26))
        exit_button = MatchResult(Path("exit_button.png"), 1.0, (590, 477), (564, 460, 53, 35))
        script = [
            ("final_done_zero.png", None),
            ("accept_result_button.png", accept),
            ("final_done_zero.png", None),
            ("accept_result_button.png", None),
            ("yes_button.png", yes),
            ("final_done_zero.png", done),
            ("exit_button.png", exit_button),
        ]
        context = SimpleNamespace(controller=controller, matcher=ScriptedTemplateMatcher(script), logger=None)
        task = AbyssTask(context)
        sleeps = []

        with patch("src.tasks.abyss.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            task._run_post_battle_result_sequence()

        self.assertEqual(sleeps[0], task.POST_RESULT_ACCEPT_WAIT_SECONDS)
        self.assertIn(task.POST_RESULT_WAIT_SECONDS, sleeps)
        self.assertEqual(controller.taps, [(368, 478), (590, 398), (590, 477)])

    def test_post_battle_result_retries_exit_until_result_closes(self):
        controller = FakeController()
        done = MatchResult(Path("final_done_zero.png"), 1.0, (408, 477), (393, 466, 40, 26))
        exit_button = MatchResult(Path("exit_button.png"), 1.0, (590, 477), (564, 460, 53, 35))
        script = [
            ("final_done_zero.png", done),
            ("exit_button.png", exit_button),
            ("final_done_zero.png", done),
            ("exit_button.png", exit_button),
            ("exit_button.png", exit_button),
            ("final_done_zero.png", None),
            ("exit_button.png", None),
        ]
        context = SimpleNamespace(controller=controller, matcher=ScriptedTemplateMatcher(script), logger=None)
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._run_post_battle_result_sequence()

        self.assertEqual(controller.taps, [(590, 477), (590, 477)])

    def test_forest_tab_uses_blue_box_roi_center(self):
        controller = FakeController()
        context = SimpleNamespace(controller=controller, matcher=FakeMatcher([]), logger=None)
        task = AbyssTask(context)

        with patch("src.tasks.abyss.time.sleep"):
            task._tap_forest_if_visible()

        self.assertEqual(controller.taps, [(507, 466)])

    def test_probe_output_wraps_power_text_in_angle_brackets(self):
        row = SimpleNamespace(
            scan_index=1,
            row_index=3,
            power_text="1,251,610",
            power_k=1251,
            confidence=1.0,
            rent_available=True,
            rent_center=(746, 358),
            rent_confidence=0.9843,
            rent_brightness_ratio=1.0,
            crop_path=Path("01_03_power.png"),
        )

        line = _format_abyss_rental_row(row)

        self.assertEqual(
            line,
            "scan=01 row=3 power=<1,251,610> ocr_conf=1.0000 rent_conf=0.9843 rent_bright=1.0000 file=01_03_power.png",
        )


if __name__ == "__main__":
    unittest.main()
