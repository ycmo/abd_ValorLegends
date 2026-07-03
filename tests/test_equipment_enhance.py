from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.tasks.equipment_enhance import EquipmentEnhanceTask


class EquipmentEnhanceTaskTests(TestCase):
    def test_select_target_hero_uses_primary_for_known_accounts(self):
        taps = []
        task = EquipmentEnhanceTask(
            context=SimpleNamespace(controller=SimpleNamespace(tap=lambda x, y: taps.append((x, y))))
        )
        task._ensure_hero_list_filter = lambda: None
        task._match_task_asset = lambda asset_name, **_kwargs: SimpleNamespace(center=(11, 22)) if asset_name == "hero_primary.png" else None
        task._match_top_left_fallback_hero = lambda: self.fail("primary account should try primary hero first")

        with patch("src.tasks.equipment_enhance.read_current_account", return_value="em3"), \
             patch("src.tasks.equipment_enhance.time.sleep"):
            task._select_target_hero()

        self.assertEqual(taps, [(11, 22)])

    def test_select_target_hero_uses_fallback_for_other_accounts(self):
        taps = []
        task = EquipmentEnhanceTask(
            context=SimpleNamespace(controller=SimpleNamespace(tap=lambda x, y: taps.append((x, y))))
        )
        task._ensure_hero_list_filter = lambda: None
        task._match_task_asset = lambda *_args, **_kwargs: self.fail("non-primary account should not search primary hero")
        task._match_top_left_fallback_hero = lambda: SimpleNamespace(center=(33, 44))

        with patch("src.tasks.equipment_enhance.read_current_account", return_value="311"), \
             patch("src.tasks.equipment_enhance.time.sleep"):
            task._select_target_hero()

        self.assertEqual(taps, [(33, 44)])

    def test_select_target_hero_opens_hero_list_when_current_screen_is_main(self):
        taps = []
        task = EquipmentEnhanceTask(
            context=SimpleNamespace(controller=SimpleNamespace(tap=lambda x, y: taps.append((x, y))))
        )
        task._ensure_hero_list_filter = lambda: None
        fallback_results = [None, SimpleNamespace(center=(55, 66))]
        task._match_task_asset = lambda *_args, **_kwargs: None
        task._match_top_left_fallback_hero = lambda: fallback_results.pop(0)
        task._open_hero_list = lambda: taps.append(("hero_tab",))

        with patch("src.tasks.equipment_enhance.read_current_account", return_value="311"), \
             patch("src.tasks.equipment_enhance.time.sleep"):
            task._select_target_hero()

        self.assertEqual(taps, [("hero_tab",), (55, 66)])

    def test_ensure_hero_list_filter_taps_evil_filter(self):
        task = EquipmentEnhanceTask(context=SimpleNamespace())
        events = []
        task._match_task_asset = lambda asset_name, **_kwargs: object() if asset_name == "evil_filter.png" else None
        task._open_hero_list = lambda: events.append("open_hero_list")
        task._tap_task_asset = lambda label, asset_name, **_kwargs: events.append((label, asset_name))

        task._ensure_hero_list_filter()

        self.assertEqual(events, [("select evil hero filter", "evil_filter.png")])

    def test_return_to_daily_tasks_uses_hero_route(self):
        events = []
        task = EquipmentEnhanceTask(
            context=SimpleNamespace(
                navigator=SimpleNamespace(go_to_daily_tasks=lambda max_steps=4: events.append(("go_daily", max_steps)) or True),
                detector=SimpleNamespace(),
                controller=SimpleNamespace(screenshot=lambda: object()),
            )
        )
        visible = {
            "auto_add_button.png": None,
            "hero_info_back_button.png": object(),
        }
        task._is_daily_tasks_visible = lambda: False
        task._match_task_asset = lambda asset_name, **_kwargs: visible.get(asset_name)
        task._match_shared_asset = lambda asset_name, **_kwargs: None
        task._tap_task_asset = lambda label, asset_name, **_kwargs: events.append((label, asset_name))
        task._tap_shared_asset = lambda label, asset_name, **_kwargs: events.append((label, asset_name))
        task._tap_idle_tab = lambda: events.append("tap_idle")
        task._tap_daily_entry_from_idle = lambda: events.append("tap_daily_entry")

        task._return_to_daily_tasks()

        self.assertEqual(
            events,
            [
                ("back from hero equipment", "hero_info_back_button.png"),
                "tap_idle",
                "tap_daily_entry",
                ("go_daily", 4),
            ],
        )

    def test_tap_idle_tab_uses_clean_template(self):
        events = []
        match = SimpleNamespace(center=(468, 514), bbox=(416, 492, 104, 44), confidence=1.0)
        task = EquipmentEnhanceTask(
            context=SimpleNamespace(
                controller=SimpleNamespace(
                    tap=lambda x, y: events.append(("tap", x, y)),
                    annotate_next_tap_debug=lambda **kwargs: events.append(("annotate", kwargs)),
                )
            )
        )
        task._match_task_asset = lambda asset_name, **kwargs: match if asset_name == "idle_tab.png" else None

        with patch("src.tasks.equipment_enhance.time.sleep"):
            task._tap_idle_tab()

        self.assertEqual(events[-1], ("tap", 468, 514))

    def test_tap_daily_entry_from_idle_uses_low_threshold_template(self):
        events = []
        match = SimpleNamespace(center=(920, 49), bbox=(895, 20, 51, 58), confidence=0.708)
        task = EquipmentEnhanceTask(
            context=SimpleNamespace(
                controller=SimpleNamespace(
                    tap=lambda x, y: events.append(("tap", x, y)),
                    annotate_next_tap_debug=lambda **kwargs: events.append(("annotate", kwargs)),
                )
            )
        )
        task._match_shared_asset = lambda asset_name, **kwargs: match if asset_name == "daily_tasks_entry_alt.png" else None

        with patch("src.tasks.equipment_enhance.time.sleep"):
            task._tap_daily_entry_from_idle()

        self.assertEqual(events[-1], ("tap", 920, 49))
