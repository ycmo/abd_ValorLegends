from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.exceptions import TaskFailedError
from src.tasks.guild_dungeon import GuildDungeonTask
from src.vision_matcher import MatchResult


class FakeController:
    def __init__(self):
        self.taps = []
        self.debug_saves = []

    def screenshot(self):
        return "screen"

    def tap(self, x, y):
        self.taps.append((x, y))

    def annotate_next_tap_debug(self, **_kwargs):
        return None

    def save_annotated_debug(self, *args, **kwargs):
        self.debug_saves.append((args, kwargs))
        return None


class FakeMatcher:
    def __init__(self, *, all_matches=None, matches=None):
        self.all_matches = all_matches or {}
        self.matches = matches or {}

    def match_template_all(self, _screen, path, **_kwargs):
        return list(self.all_matches.get(path.name, ()))

    def match_template(self, _screen, path, **_kwargs):
        return self.matches.get(path.name)


class FakeNavigator:
    def __init__(self, results=None):
        self.calls = []
        self.results = iter(results or [True])

    def return_to_daily_tasks_from_known_route(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.results)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, message):
        self.messages.append(message)


class GuildDungeonTaskTests(unittest.TestCase):
    def test_missing_assets_includes_shared_battle_ready_anchor(self):
        task = GuildDungeonTask(SimpleNamespace())

        with patch.object(task, "BATTLE_READY_ASSET", Path("missing_battle_ready_anchor.png")):
            missing = task.missing_assets()

        self.assertIn(Path("missing_battle_ready_anchor.png"), missing)

    def test_map_targets_prefer_sword_over_flags(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    all_matches={
                        "sword_node_anchor.png": [_match("sword_node_anchor.png", 600, 100)],
                        "flag_node_anchor.png": [_match("flag_node_anchor.png", 500, 100)],
                    }
                ),
            )
        )

        targets = task._find_map_targets("screen")

        self.assertEqual([target.kind for target in targets], ["sword", "flag"])
        self.assertEqual(targets[0].match.center, (600, 100))
        self.assertEqual(targets[1].match.center, (500, 100))

    def test_remaining_attempt_selects_same_column_challenge(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    all_matches={
                        "remaining_attempt_anchor.png": [
                            _match("remaining_attempt_anchor.png", 390, 374),
                        ],
                        "challenge_button.png": [
                            _match("challenge_button.png", 193, 336),
                            _match("challenge_button.png", 389, 336),
                            _match("challenge_button.png", 584, 336),
                        ],
                    }
                ),
            )
        )

        selected = task._find_challenge_for_remaining_attempt("screen")

        self.assertIsNotNone(selected)
        self.assertEqual(selected.center, (389, 336))

    def test_probe_target_records_debug_summary(self):
        controller = FakeController()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    all_matches={
                        "sword_node_anchor.png": [_match("sword_node_anchor.png", 600, 100)],
                        "remaining_attempt_anchor.png": [_match("remaining_attempt_anchor.png", 390, 374)],
                        "challenge_button.png": [_match("challenge_button.png", 389, 336)],
                    }
                ),
            )
        )

        with patch("src.tasks.guild_dungeon.time.sleep"):
            message = task.probe_target_from_current_map(tap_challenge=True)

        self.assertIn("target selected", message)
        self.assertEqual(len(task.last_probe_records), 1)
        self.assertEqual(task.last_probe_records[0].node_kind, "sword")
        self.assertEqual(task.last_probe_records[0].selected_center, (389, 336))
        self.assertTrue(task.last_probe_summary_path.exists())

    def test_bonus_reward_column_is_preferred(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    all_matches={
                        "remaining_attempt_anchor.png": [
                            _match("remaining_attempt_anchor.png", 193, 374),
                            _match("remaining_attempt_anchor.png", 389, 374),
                        ],
                        "challenge_button.png": [
                            _match("challenge_button.png", 193, 336),
                            _match("challenge_button.png", 389, 336),
                        ],
                        "bonus_reward_anchor.png": [
                            _match("bonus_reward_anchor.png", 389, 166),
                        ],
                    }
                ),
            )
        )

        selected = task._find_challenge_for_remaining_attempt("screen")

        self.assertIsNotNone(selected)
        self.assertEqual(selected.center, (389, 336))

    def test_select_challenge_from_open_outpost_taps_without_map_probe(self):
        controller = FakeController()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    all_matches={
                        "remaining_attempt_anchor.png": [_match("remaining_attempt_anchor.png", 389, 374)],
                        "challenge_button.png": [_match("challenge_button.png", 389, 336)],
                    }
                ),
            )
        )

        message = task._select_challenge_from_open_outpost(tap_challenge=True)

        self.assertIn("open outpost", message)
        self.assertEqual(controller.taps, [(389, 336)])

    def test_wait_for_battle_continue_taps_continue_button(self):
        controller = FakeController()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "continue_button.png": _match("continue_button.png", 480, 482),
                    }
                ),
            )
        )

        with patch("src.tasks.guild_dungeon.time.sleep"):
            task._wait_for_battle_continue()

        self.assertEqual(controller.taps, [(480, 482)])

    def test_start_battle_from_ready_screen_taps_bottom_right_challenge(self):
        controller = FakeController()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "battle_ready_anchor.png": _match("battle_ready_anchor.png", 900, 480),
                    }
                ),
            )
        )

        with patch("src.tasks.guild_dungeon.time.sleep"):
            task._start_battle_from_ready_screen()

        self.assertEqual(controller.taps, [GuildDungeonTask.START_BATTLE_POINT])

    def test_return_closes_open_outpost_then_uses_shared_first_back_asset(self):
        controller = FakeController()
        navigator = FakeNavigator()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "outpost_close_button.png": _match("outpost_close_button.png", 830, 48),
                    }
                ),
                navigator=navigator,
            )
        )

        with patch("src.tasks.guild_dungeon.time.sleep"):
            self.assertTrue(task._return_to_daily_tasks())

        self.assertEqual(controller.taps, [(830, 48)])
        self.assertEqual(navigator.calls[0]["max_back_taps"], 4)
        self.assertEqual(navigator.calls[0]["back_asset"].name, "back_button2.png")

    def test_return_uses_guild_back_asset_after_shared_back_stops(self):
        navigator = FakeNavigator(results=[False, True])
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(),
                navigator=navigator,
            )
        )

        self.assertTrue(task._return_to_daily_tasks())

        self.assertEqual(len(navigator.calls), 2)
        self.assertEqual(navigator.calls[0]["back_asset"].name, "back_button2.png")
        self.assertEqual(navigator.calls[1]["back_asset"].name, "back_button.png")

    def test_daily_attempts_exhausted_detects_zero_counter(self):
        controller = FakeController()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "map_title_anchor.png": _match("map_title_anchor.png", 127, 38),
                        "remaining_attempts_zero_anchor.png": _match("remaining_attempts_zero_anchor.png", 130, 95),
                    }
                ),
            )
        )

        self.assertTrue(task._daily_attempts_exhausted("screen"))
        self.assertEqual(controller.debug_saves[0][0][0], "guild_dungeon_daily_attempts_zero_probe")
        self.assertIn("confidence=0.9500", controller.debug_saves[0][1]["lines"][2])
        self.assertEqual(controller.debug_saves[0][1]["panel_position"], "right")

    def test_daily_attempts_zero_probe_below_threshold_is_not_exhausted(self):
        controller = FakeController()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "remaining_attempts_zero_anchor.png": MatchResult(
                            template_path=Path("remaining_attempts_zero_anchor.png"),
                            confidence=0.42,
                            center=(130, 95),
                            bbox=(121, 86, 18, 18),
                        ),
                    }
                ),
            )
        )

        self.assertFalse(task._daily_attempts_exhausted("screen"))
        self.assertIn("threshold=0.8600", controller.debug_saves[0][1]["lines"][2])

    def test_daily_attempts_zero_probe_logs_console_debug_message(self):
        logger = FakeLogger()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "map_title_anchor.png": _match("map_title_anchor.png", 127, 38),
                        "remaining_attempts_zero_anchor.png": _match("remaining_attempts_zero_anchor.png", 130, 95),
                    }
                ),
                logger=logger,
            )
        )

        task._daily_attempts_exhausted("screen")

        self.assertIn("Guild dungeon daily attempts zero probe", logger.messages[0])
        self.assertIn("confidence=0.9500", logger.messages[0])

    def test_battle_ready_counts_as_current_task_scene(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "battle_ready_anchor.png": _match("battle_ready_anchor.png", 900, 480),
                    }
                ),
            )
        )

        self.assertTrue(task.is_task_scene("screen"))

    def test_map_title_counts_as_current_task_scene(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "map_title_anchor.png": _match("map_title_anchor.png", 127, 38),
                    }
                ),
            )
        )

        self.assertTrue(task.is_task_scene("screen"))

    def test_wait_for_map_accepts_open_outpost(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "outpost_close_button.png": _match("outpost_close_button.png", 830, 48),
                    }
                ),
            )
        )

        with patch("src.tasks.guild_dungeon.time.sleep"):
            task._wait_for_map_screen("after battle", timeout_seconds=0.1)

    def test_execute_from_battle_ready_skips_map_probe(self):
        controller = FakeController()
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=controller,
                matcher=FakeMatcher(
                    matches={
                        "battle_ready_anchor.png": _match("battle_ready_anchor.png", 900, 480),
                        "continue_button.png": _match("continue_button.png", 480, 482),
                    }
                ),
                navigator=FakeNavigator(),
            )
        )
        task.TARGET_BATTLES = 1

        with patch("src.tasks.guild_dungeon.time.sleep"), \
             patch.object(task, "probe_target_from_current_map", side_effect=AssertionError("should not probe map")):
            message = task.execute()

        self.assertIn("continued from battle ready", message)
        self.assertEqual(controller.taps, [GuildDungeonTask.START_BATTLE_POINT, (480, 482)])

    def test_execute_returns_when_daily_attempts_are_zero(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "map_title_anchor.png": _match("map_title_anchor.png", 127, 38),
                        "remaining_attempts_zero_anchor.png": _match("remaining_attempts_zero_anchor.png", 130, 95),
                    }
                ),
                navigator=FakeNavigator(),
            )
        )

        with patch.object(task, "probe_target_from_current_map", side_effect=AssertionError("should not probe")), \
             patch.object(task, "_start_battle_from_ready_screen", side_effect=AssertionError("should not start")):
            message = task.execute()

        self.assertIn("completed=0", message)
        self.assertIn("daily remaining attempts exhausted", message)

    def test_execute_ignores_zero_like_icon_while_outpost_is_open(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(
                    matches={
                        "map_title_anchor.png": _match("map_title_anchor.png", 127, 38),
                        "outpost_close_button.png": _match("outpost_close_button.png", 830, 48),
                        "remaining_attempts_zero_anchor.png": _match("remaining_attempts_zero_anchor.png", 130, 95),
                    }
                ),
                navigator=FakeNavigator(),
            )
        )
        task.TARGET_BATTLES = 1

        with patch.object(task, "_select_challenge_from_open_outpost", return_value="open outpost target"), \
             patch.object(task, "_start_battle_from_ready_screen"), \
             patch.object(task, "_wait_for_battle_continue"):
            message = task.execute()

        self.assertIn("completed=1", message)
        self.assertEqual(task.context.controller.debug_saves, [])

    def test_execute_runs_two_battles_and_rechecks_map_between_them(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(),
                navigator=FakeNavigator(),
            )
        )

        with patch("src.tasks.guild_dungeon.time.sleep"), \
             patch.object(task, "_is_battle_ready_screen", return_value=False), \
             patch.object(task, "_select_challenge_from_open_outpost", return_value=None) as select_open, \
             patch.object(
                  task,
                  "probe_target_from_current_map",
                  side_effect=["target one", "target two"],
              ) as probe, \
             patch.object(task, "_start_battle_from_ready_screen") as start_battle, \
             patch.object(task, "_wait_for_battle_continue") as wait_continue, \
             patch.object(task, "_wait_for_map_screen") as wait_map:
            message = task.execute()

        self.assertIn("completed=2", message)
        self.assertEqual(select_open.call_count, 2)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(start_battle.call_count, 2)
        self.assertEqual(wait_continue.call_count, 2)
        self.assertEqual(wait_map.call_count, 1)

    def test_execute_stops_after_three_flow_failures(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(),
                navigator=FakeNavigator(),
            )
        )

        with patch("src.tasks.guild_dungeon.time.sleep"), \
             patch.object(task, "_is_battle_ready_screen", return_value=False), \
             patch.object(task, "probe_target_from_current_map", side_effect=TaskFailedError("no target")):
            with self.assertRaises(TaskFailedError) as context:
                task.execute()

        self.assertIn("failed 3 time", str(context.exception))

    def test_start_battle_from_ready_screen_times_out(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(),
            )
        )

        with patch("src.tasks.guild_dungeon.time.time", side_effect=[0, 21]), \
             patch("src.tasks.guild_dungeon.time.sleep"):
            with self.assertRaises(TaskFailedError):
                task._start_battle_from_ready_screen()

    def test_wait_for_battle_continue_times_out(self):
        task = GuildDungeonTask(
            SimpleNamespace(
                controller=FakeController(),
                matcher=FakeMatcher(),
            )
        )

        with patch("src.tasks.guild_dungeon.time.time", side_effect=[0, 151]), \
             patch("src.tasks.guild_dungeon.time.sleep"):
            with self.assertRaises(TaskFailedError):
                task._wait_for_battle_continue()


def _match(name: str, x: int, y: int) -> MatchResult:
    return MatchResult(
        template_path=Path(name),
        confidence=0.95,
        center=(x, y),
        bbox=(x - 20, y - 10, 40, 20),
    )


if __name__ == "__main__":
    unittest.main()
