import unittest
from pathlib import Path
from types import SimpleNamespace

from src.exceptions import TaskFailedError
from src.tasks.endless_trial import EndlessTrialScene, EndlessTrialTask
from src.vision_matcher import MatchResult


class FakeController:
    def __init__(self, screens):
        self.screens = list(screens)
        self.taps = []

    def screenshot(self):
        if not self.screens:
            return "unknown"
        return self.screens.pop(0)

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeMatcher:
    def match_template(self, screen, path, threshold=None, **kwargs):
        if isinstance(screen, EndlessTrialScene) and path.name == EndlessTrialTask.SCENE_TEMPLATES[screen][0]:
            return MatchResult(Path(path), 0.99, (10, 10), (0, 0, 20, 20))
        return None


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, message, force=False):
        self.messages.append(message)


class FakeEndlessTrialTask(EndlessTrialTask):
    def __init__(self, screens):
        self.logger = FakeLogger()
        context = SimpleNamespace(
            controller=FakeController(screens),
            matcher=FakeMatcher(),
            logger=self.logger,
        )
        super().__init__(context)
        self.sleeps = []

    def _sleep(self, seconds):
        self.sleeps.append(seconds)

    def missing_assets(self):
        return ()


class AmbiguousLobbyMatcher:
    def match_template(self, screen, path, threshold=None, **kwargs):
        if screen == "ambiguous_lobby" and path.name == "trial_lobby_anchor.png":
            return MatchResult(Path(path), 0.91, (10, 10), (0, 0, 20, 20))
        if screen == "ambiguous_lobby" and path.name == "trial_lobby_post_anchor.png":
            return MatchResult(Path(path), 0.99, (10, 10), (0, 0, 20, 20))
        if screen == "later_state" and path.name == "stage_popup_anchor.png":
            return MatchResult(Path(path), 0.99, (10, 10), (0, 0, 20, 20))
        if screen == "later_state" and path.name == "battle_ready_anchor.png":
            return MatchResult(Path(path), 0.90, (10, 10), (0, 0, 20, 20))
        return None


class EndlessTrialRouteTests(unittest.TestCase):
    def test_detect_route_scene_prefers_route_order_over_highest_confidence(self):
        context = SimpleNamespace(matcher=AmbiguousLobbyMatcher())
        task = EndlessTrialTask(context)

        scene, match = task.detect_route_scene("ambiguous_lobby")

        self.assertEqual(scene, EndlessTrialScene.TRIAL_LOBBY)
        self.assertEqual(match.confidence, 0.91)

    def test_detect_route_scene_does_not_search_before_current_state(self):
        context = SimpleNamespace(matcher=AmbiguousLobbyMatcher())
        task = EndlessTrialTask(context)

        scene, match = task.detect_route_scene("later_state", start_at=EndlessTrialScene.BATTLE_READY)

        self.assertEqual(scene, EndlessTrialScene.BATTLE_READY)
        self.assertEqual(match.confidence, 0.90)

    def test_execute_win_route_uses_legacy_verified_points(self):
        task = FakeEndlessTrialTask(
            [
                EndlessTrialScene.TRIAL_LOBBY,
                EndlessTrialScene.STAGE_DETAILS,
                EndlessTrialScene.STAGE_TEAM_GROUPING,
                EndlessTrialScene.BATTLE_READY,
                "combat-unknown",
                EndlessTrialScene.BATTLE_END,
                EndlessTrialScene.TRIAL_LOBBY_POST,
            ]
        )

        message = task.execute()

        self.assertIn("endless trial completed", message)
        self.assertIn("battle_result=win", message)
        self.assertEqual(
            task.context.controller.taps,
            [
                (190, 270),
                (898, 509),
                (690, 412),
                (902, 480),
                (480, 480),
                (61, 22),
            ],
        )

    def test_execute_failure_route_closes_result_and_backs_out(self):
        task = FakeEndlessTrialTask(
            [
                EndlessTrialScene.TRIAL_LOBBY,
                EndlessTrialScene.STAGE_DETAILS,
                EndlessTrialScene.BATTLE_READY,
                EndlessTrialScene.BATTLE_FAIL,
                EndlessTrialScene.BATTLE_READY,
                EndlessTrialScene.STAGE_DETAILS_POST,
                EndlessTrialScene.EXIT_CONFIRM,
                EndlessTrialScene.TRIAL_LOBBY_POST,
            ]
        )

        message = task.execute()

        self.assertIn("endless trial completed", message)
        self.assertIn("battle_result=loss", message)
        self.assertEqual(
            task.context.controller.taps,
            [
                (190, 270),
                (898, 509),
                (902, 480),
                (479, 507),
                (61, 22),
                (61, 22),
                (589, 401),
                (61, 22),
            ],
        )

    def test_unknown_scene_stops_without_tapping_forever(self):
        task = FakeEndlessTrialTask(["unknown"] * 8)

        with self.assertRaises(TaskFailedError):
            task.execute()

        self.assertEqual(task.context.controller.taps, [])


if __name__ == "__main__":
    unittest.main()
