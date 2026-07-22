from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2

from src.config import TASK_SPECS
from src.tasks.hero_reroll_loop import HeroRerollLoopTask, set_hero_reroll_target_count
from src.vision_matcher import VisionMatcher, read_image


class FakeController:
    serial = "fake-serial"

    def __init__(self, screen):
        self._screen = screen
        self.taps = []
        self.debug_annotations = []

    def screenshot(self):
        return self._screen.copy()

    def tap(self, x, y):
        self.taps.append((int(x), int(y)))

    def annotate_next_tap_debug(self, **kwargs):
        self.debug_annotations.append(kwargs)


class FakeContext:
    def __init__(self, screen):
        self.controller = FakeController(screen)
        self.matcher = VisionMatcher()
        self.logger = None
        self.finder = None
        self.navigator = None
        self.detector = None
        self.battle = None
        self.blocker = None


class SequenceController(FakeController):
    def __init__(self, screens):
        super().__init__(screens[-1])
        self._screens = list(screens)
        self._index = 0

    def screenshot(self):
        if self._index < len(self._screens):
            screen = self._screens[self._index]
            self._index += 1
            return screen.copy()
        return self._screens[-1].copy()


class SequenceContext(FakeContext):
    def __init__(self, screens):
        self.controller = SequenceController(screens)
        self.matcher = VisionMatcher()
        self.logger = None
        self.finder = None
        self.navigator = None
        self.detector = None
        self.battle = None
        self.blocker = None


class HeroRerollLoopTests(unittest.TestCase):
    frames = Path("manual_screenshots") / "hero_reroll_video_frames"
    simple_frames = Path("manual_screenshots") / "hero_reroll_simple_flow_20260719"

    def read_frame(self, name: str):
        image = read_image(self.frames / name, cv2.IMREAD_COLOR)
        return cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA)

    def read_simple_frame(self, name: str):
        return read_image(self.simple_frames / name, cv2.IMREAD_COLOR)

    def tearDown(self):
        set_hero_reroll_target_count(None)

    def test_task_spec_is_independent(self):
        self.assertEqual(TASK_SPECS["hero_reroll_loop"].kind, "independent")

    def test_required_assets_exist(self):
        screen = self.read_frame("000s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        self.assertEqual(task.missing_assets(), ())

    def test_counts_target_heroes_on_list(self):
        screen = self.read_frame("090s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        self.assertTrue(task.is_hero_list_visible(screen))
        self.assertEqual(task.count_target_heroes(screen), 5)

    def test_duplicate_yellow_five_star_starter_is_found_when_target_pair_is_unavailable(self):
        screen = self.read_frame("000s.png")
        task = HeroRerollLoopTask(FakeContext(screen))
        for match in task._target_matches_on_list(screen):
            x, y, width, height = match.bbox
            screen[y : y + height, x : x + width] = 0

        starter = task._find_duplicate_yellow_five_star_starter(screen)

        self.assertIsNotNone(starter)
        assert starter is not None
        self.assertNotEqual(starter.center, (75, 91))
        self.assertNotEqual(starter.center, (525, 181))

    def test_material_candidate_uses_any_yellow_five_star_except_target(self):
        screen = self.read_frame("006s.png")
        task = HeroRerollLoopTask(FakeContext(screen))
        task._current_starter_identity = task._card_identity_crop(screen, (349, 132))
        task._current_starter_is_target = False

        candidate = task._find_material_candidate(screen, {(349, 132)})

        self.assertIsNotNone(candidate)
        assert candidate is not None
        target_centers = {match.center for match in task.context.matcher.match_template_all(
            screen,
            task.asset_path("target_dabi_face.png"),
            threshold=task.TARGET_FACE_MATCH_THRESHOLD,
            roi=task.MATERIAL_DIALOG_ROI,
            check_brightness=False,
            max_results=10,
            min_center_distance=55,
        )}
        self.assertFalse(task._is_near_any(candidate.center, target_centers))

    def test_material_candidate_excludes_target_hero(self):
        screen = self.read_frame("056s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        candidate = task._find_material_candidate(screen, set())

        self.assertIsNotNone(candidate)
        assert candidate is not None
        target_centers = {match.center for match in task.context.matcher.match_template_all(
            screen,
            task.asset_path("target_dabi_face.png"),
            threshold=task.TARGET_FACE_MATCH_THRESHOLD,
            roi=task.MATERIAL_DIALOG_ROI,
            check_brightness=False,
            max_results=10,
            min_center_distance=55,
        )}
        self.assertFalse(task._is_near_any(candidate.center, target_centers))

    def test_material_candidate_falls_back_to_yellow_five_star(self):
        screen = self.read_frame("006s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        candidate = task._find_material_candidate(screen, set())

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertIn(candidate.center, HeroRerollLoopTask.MATERIAL_CARD_CENTERS)

    def test_active_material_slot_detects_two_material_requirement(self):
        screen = self.read_frame("076s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        self.assertEqual(task._find_active_material_slot(screen), ((839, 319), 2))

    def test_active_material_slot_ignores_four_material_requirement(self):
        screen = self.read_simple_frame("030s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        self.assertIsNone(task._find_active_material_slot(screen))

    def test_reset_tab_asset_matches_unselected_reset_tab(self):
        screen = self.read_simple_frame("034s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        match = task.context.matcher.match_template(
            screen,
            task.asset_path("hero_reset_tab.png"),
            threshold=0.86,
            roi=(0, 80, 130, 130),
            check_brightness=False,
        )

        self.assertIsNotNone(match)

    def test_awaken_confirm_popup_uses_shared_confirm_button(self):
        screen = self.read_simple_frame("019s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        handled = task._tap_confirm_button_if_visible("awaken_confirm")

        self.assertTrue(handled)
        self.assertEqual(task.context.controller.taps, [(589, 402)])

    def test_awaken_confirm_ignores_transient_hero_info_until_success(self):
        confirm = self.read_simple_frame("019s.png")
        transient_hero_info = read_image(
            Path("log")
            / "20260719_115705_82532_hero_reroll_loop"
            / "000052_20260719_115831_after_tap_589_402.png",
            cv2.IMREAD_COLOR,
        )
        success = self.read_simple_frame("027s.png")
        context = SequenceContext([confirm, confirm, transient_hero_info, transient_hero_info, success, success])
        task = HeroRerollLoopTask(context)
        fake_now = [0.0]

        def advance(seconds):
            fake_now[0] += seconds

        with patch("src.tasks.hero_reroll_loop.time.time", side_effect=lambda: fake_now[0]), \
             patch("src.tasks.hero_reroll_loop.time.sleep", side_effect=advance):
            outcome = task._wait_after_awaken_tap()

        self.assertEqual(outcome, "success")
        self.assertEqual(context.controller.taps, [(589, 402)])

    def test_awaken_wait_ignores_initial_hero_info_without_confirm(self):
        transient_hero_info = read_image(
            Path("log")
            / "20260719_142833_100476_hero_reroll_loop"
            / "000016_20260719_142900_after_tap_795_469.png",
            cv2.IMREAD_COLOR,
        )
        success = self.read_simple_frame("027s.png")
        context = SequenceContext([transient_hero_info, transient_hero_info, success, success])
        task = HeroRerollLoopTask(context)
        fake_now = [0.0]

        def advance(seconds):
            fake_now[0] += seconds

        with patch("src.tasks.hero_reroll_loop.time.time", side_effect=lambda: fake_now[0]), \
             patch("src.tasks.hero_reroll_loop.time.sleep", side_effect=advance):
            outcome = task._wait_after_awaken_tap()

        self.assertEqual(outcome, "success")
        self.assertEqual(context.controller.taps, [])

    def test_active_material_slot_is_none_when_materials_are_full(self):
        screen = self.read_frame("024s.png")
        task = HeroRerollLoopTask(FakeContext(screen))

        self.assertIsNone(task._find_active_material_slot(screen))


if __name__ == "__main__":
    unittest.main()
