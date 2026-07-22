from __future__ import annotations

import unittest
from pathlib import Path

import cv2

from src.ui.blockers import BlockerHandler
from src.config import TASK_SPECS
from src.tasks.wild_treasure import WildTreasureTask, set_wild_treasure_start_override
from src.vision_matcher import VisionMatcher, read_image


class FakeController:
    serial = "fake-serial"

    def __init__(self, screen):
        self._screen = screen
        self.taps = []
        self.long_presses = []
        self.swipes = []
        self.debug_annotations = []

    def screenshot(self):
        return self._screen.copy()

    def tap(self, x, y):
        self.taps.append((int(x), int(y)))

    def long_press(self, x, y, duration_ms=800):
        self.long_presses.append((int(x), int(y), int(duration_ms)))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((int(x1), int(y1), int(x2), int(y2), int(duration_ms)))

    def annotate_next_tap_debug(self, **kwargs):
        self.debug_annotations.append(kwargs)


class SequenceController(FakeController):
    def __init__(self, screens):
        super().__init__(screens[0])
        self._screens = list(screens)
        self._index = 0

    def screenshot(self):
        screen = self._screens[min(self._index, len(self._screens) - 1)]
        self._index += 1
        return screen.copy()


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


class SequenceContext(FakeContext):
    def __init__(self, screens):
        super().__init__(screens[0])
        self.controller = SequenceController(screens)
        self.blocker = BlockerHandler(self.controller)


class WildTreasureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = next(
            path
            for path in Path("manual_screenshots").iterdir()
            if path.is_dir()
            and {"000.png", "001.png", "002.png", "013.png"}.issubset(
                {item.name for item in path.glob("*.png")}
            )
        )

    def tearDown(self):
        set_wild_treasure_start_override(None)

    def test_task_spec_is_independent(self):
        self.assertEqual(TASK_SPECS["wild_treasure"].kind, "independent")

    def test_required_assets_exist(self):
        screen = read_image(self.base / "002.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        self.assertEqual(task.missing_assets(), ())

    def test_scene_anchors_match_manual_screenshots(self):
        cases = [
            ("002.png", lambda task, screen: task.is_task_scene(screen)),
            ("008.png", lambda task, screen: task.is_hero_list_visible(screen)),
            ("009.png", lambda task, screen: task.is_hero_info_visible(screen)),
            ("022.png", lambda task, screen: task.is_ascend_available(screen)),
            ("023.png", lambda task, screen: task.is_ascend_dialog_visible(screen)),
            ("011.png", lambda task, screen: task.is_battle_setup_visible(screen)),
            ("012.png", lambda task, screen: task.is_victory_visible(screen)),
            ("013.png", lambda task, screen: task.is_activation_success_visible(screen)),
        ]
        for filename, predicate in cases:
            with self.subTest(filename=filename):
                screen = read_image(self.base / filename, cv2.IMREAD_COLOR)
                task = WildTreasureTask(FakeContext(screen))

                self.assertTrue(predicate(task, screen))

    def test_battle_event_target_is_found_after_exploration(self):
        screen = read_image(self.base / "010.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        match = task.find_battle_event(screen)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreater(match.confidence, 0.99)
        self.assertEqual(match.center, (474, 240))
        self.assertEqual(task._battle_event_tap_point(match), (474, 269))

    def test_battle_event_target_does_not_match_exploration_tile(self):
        screen = read_image(self.base / "005.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        self.assertIsNone(task.find_battle_event(screen))

    def test_activation_overlay_is_not_treated_as_plain_map(self):
        screen = read_image(self.base / "013.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        self.assertFalse(task.is_task_scene(screen))
        self.assertTrue(task.is_activation_success_visible(screen))

    def test_shared_got_blocker_detects_wild_reward_overlays(self):
        handler = BlockerHandler(FakeController(read_image(self.base / "002.png", cv2.IMREAD_COLOR)))

        item = handler.match_reward_acquired(read_image(self.base / "003.png", cv2.IMREAD_COLOR))
        hero = handler.match_reward_acquired(read_image(self.base / "004.png", cv2.IMREAD_COLOR))

        self.assertIsNotNone(item)
        self.assertIsNotNone(hero)

    def test_shared_got_blocker_does_not_match_normal_wild_map_cyan_effects(self):
        path = Path("debug") / "wild_treasure_current.png"
        if not path.exists():
            self.skipTest("current wild treasure debug screenshot is not available")
        handler = BlockerHandler(FakeController(read_image(self.base / "002.png", cv2.IMREAD_COLOR)))

        self.assertIsNone(handler.match_reward_acquired(read_image(path, cv2.IMREAD_COLOR)))

    def test_mainline_points_match_confirmed_flow(self):
        self.assertEqual(WildTreasureTask.INITIAL_EVENT.point, (393, 165))
        self.assertEqual(WildTreasureTask.HERO_BUTTON.point, (916, 503))
        self.assertEqual([hero.point for hero in WildTreasureTask.HERO_CARDS], [(75, 76), (166, 76)])
        self.assertEqual(WildTreasureTask.UPGRADE_BUTTON.point, (790, 480))
        self.assertEqual(WildTreasureTask.ASCEND_BUTTON.point, (795, 480))
        self.assertEqual(WildTreasureTask.ASCEND_CONFIRM_BUTTON.point, (481, 479))
        self.assertEqual([hero.point for hero in WildTreasureTask.FORMATION_HEROES], [
            (55, 476),
            (145, 476),
            (235, 476),
            (325, 476),
        ])
        self.assertEqual(WildTreasureTask.CHALLENGE_BUTTON.point, (910, 485))
        self.assertEqual(WildTreasureTask.CONTINUE_BUTTON.point, (480, 487))
        self.assertEqual(WildTreasureTask.ACTIVATION_GO_BUTTON.point, (594, 361))

    def test_explore_tile_is_found_from_lit_boundary(self):
        screen = read_image(self.base / "005.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        point = task.find_explore_tile(screen)

        self.assertIsNotNone(point)
        assert point is not None
        self.assertGreaterEqual(point[0], 350)
        self.assertGreaterEqual(point[1], 120)

    def test_resume_from_hero_upgrade_accepts_map_scene(self):
        set_wild_treasure_start_override("hero-upgrade")
        screen = read_image(self.base / "002.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        self.assertEqual(task.start_point(), "hero-upgrade")
        self.assertTrue(task.is_current_resume_scene())

    def test_resume_from_victory_accepts_victory_scene(self):
        set_wild_treasure_start_override("victory")
        screen = read_image(self.base / "012.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        self.assertTrue(task.is_current_resume_scene())

    def test_resume_from_skip_upgrade_accepts_map_scene(self):
        set_wild_treasure_start_override("skip-upgrade")
        screen = read_image(self.base / "005.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(FakeContext(screen))

        self.assertEqual(task.start_point(), "skip-upgrade")
        self.assertTrue(task.is_current_resume_scene())

    def test_open_hero_list_retries_after_reward_overlay_blocks_entry_tap(self):
        map_screen = read_image(self.base / "002.png", cv2.IMREAD_COLOR)
        reward_screen = read_image(self.base / "003.png", cv2.IMREAD_COLOR)
        hero_list_screen = read_image(self.base / "008.png", cv2.IMREAD_COLOR)
        task = WildTreasureTask(
            SequenceContext([map_screen, reward_screen, map_screen, map_screen, map_screen, hero_list_screen])
        )

        task._open_hero_list()

        self.assertEqual(task.context.controller.taps[0], WildTreasureTask.HERO_BUTTON.point)
        self.assertIn(WildTreasureTask.HERO_BUTTON.point, task.context.controller.taps[1:])


if __name__ == "__main__":
    unittest.main()
