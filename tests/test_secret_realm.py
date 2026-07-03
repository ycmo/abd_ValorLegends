from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.tasks.secret_realm import SecretRealmTask


class SecretRealmTaskTests(TestCase):
    def test_execute_sweeps_when_purchase_dialog_does_not_open(self):
        returned = []
        context = SimpleNamespace(
            navigator=SimpleNamespace(
                return_to_daily_tasks_from_known_route=lambda **_kwargs: returned.append(True) or True
            )
        )
        task = SecretRealmTask(context=context)
        events = []
        task._ensure_lost_forest_selected = lambda: events.append("select")
        task._try_buy_lost_forest_attempts = lambda: False
        task._tap_task_asset = lambda label, *_args, **_kwargs: events.append(label)
        task._dismiss_possible_reward_overlay = lambda: events.append("dismiss")

        message = task.execute()

        self.assertEqual(
            events,
            ["select", "sweep all", "dismiss"],
        )
        self.assertEqual(returned, [True])
        self.assertEqual(message, "Lost Forest purchase unavailable; tapped sweep all")

    def test_open_purchase_dialog_returns_false_when_plus_shows_limit_toast(self):
        task = SecretRealmTask(context=SimpleNamespace())
        events = []

        task._tap_task_asset = lambda label, *_args, **_kwargs: events.append(label)
        task._match_task_asset = lambda *_args, **_kwargs: None
        task._wait_for_realm_screen = lambda label: events.append(label)
        task._log = lambda message: events.append(message)

        self.assertFalse(task._open_purchase_dialog())
        self.assertEqual(events[0], "open purchase dialog")
        self.assertIn("after purchase dialog did not open", events)

    def test_match_task_asset_accepts_label_and_asset_name_for_legacy_calls(self):
        screens = ["screen"]
        matched = object()
        task = SecretRealmTask(
            context=SimpleNamespace(
                controller=SimpleNamespace(screenshot=lambda: screens[0]),
                matcher=SimpleNamespace(match_template=lambda *_args, **_kwargs: matched),
            )
        )

        with patch.object(task, "asset_path", return_value="asset-path"):
            self.assertIs(task._match_task_asset("label", "asset.png"), matched)
