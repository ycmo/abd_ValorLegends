"""
secret_realm.py — Secret Realm (Phase 2)
"""
from __future__ import annotations

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src_v2.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import Roi


class SecretRealmTask(BaseTask):
    spec = TASK_SPECS["secret_realm"]
    required_assets = (
        "task_label.png",
        "lost_forest_tab.png",
        "lost_forest_selected_tab.png",
        "realm_attempt_entry_plus_button.png",
        "purchase_dialog_title.png",
        "daily_purchase_count_5_5.png",
        "purchase_quantity_plus_button.png",
        "purchase_quantity_two.png",
        "purchase_confirm_button.png",
        "sweep_all_button.png",
        "secret_realm_back_button.png",
    )

    LEFT_TAB_ROI: Roi = (0, 80, 210, 330)
    REALM_ATTEMPT_PLUS_ROI: Roi = (300, 50, 55, 40)
    PURCHASE_DIALOG_ROI: Roi = (215, 70, 530, 390)
    SWEEP_ALL_ROI: Roi = (760, 390, 200, 150)
    
    task_scene_anchors = (
        TaskSceneAnchor("lost_forest_selected_tab.png", threshold=0.75, roi=LEFT_TAB_ROI),
        TaskSceneAnchor("lost_forest_tab.png", threshold=0.78, roi=LEFT_TAB_ROI),
    )

    def execute(self) -> str:
        self._ensure_lost_forest_selected()
        self._open_purchase_dialog()
        self._validate_purchase_dialog()
        self._tap(
            "set purchase quantity to 2",
            "purchase_quantity_plus_button.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.80,
            wait_after=TAP_COOLDOWN_SECONDS,
        )
        self._require(
            "purchase quantity 2",
            "purchase_quantity_two.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
        )
        self._tap(
            "confirm Lost Forest purchase",
            "purchase_confirm_button.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        self._wait_for_realm_screen("after purchase")
        self._tap(
            "sweep all",
            "sweep_all_button.png",
            roi=self.SWEEP_ALL_ROI,
            threshold=0.82,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_possible_reward_overlay()
        return "bought Lost Forest twice and tapped sweep all"

    def _ensure_lost_forest_selected(self) -> None:
        if self._wait_for(
            "lost_forest_selected_tab.png",
            roi=self.LEFT_TAB_ROI,
            threshold=0.78,
            timeout_seconds=1.0,
        ):
            return

        self._tap(
            "Lost Forest tab",
            "lost_forest_tab.png",
            roi=self.LEFT_TAB_ROI,
            threshold=0.78,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        self._wait_for_realm_screen("after selecting Lost Forest")

    def _open_purchase_dialog(self) -> None:
        self._tap(
            "open purchase dialog",
            "realm_attempt_entry_plus_button.png",
            roi=self.REALM_ATTEMPT_PLUS_ROI,
            threshold=0.78,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        self._require(
            "purchase dialog title",
            "purchase_dialog_title.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
        )

    def _validate_purchase_dialog(self) -> None:
        self._require(
            "daily purchase count 5/5",
            "daily_purchase_count_5_5.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
        )

    def _wait_for_realm_screen(self, label: str) -> None:
        if not self._wait_for(
            "lost_forest_selected_tab.png",
            roi=self.LEFT_TAB_ROI,
            threshold=0.75,
            timeout_seconds=5.0,
        ):
            raise TaskFailedError(f"Lost Forest screen not visible {label}")

    def _dismiss_possible_reward_overlay(self) -> None:
        self._dismiss_overlay_by_blank_taps(max_taps=2)

    def _pre_return_hook(self) -> None:
        self.context.navigator.return_to_daily_tasks_from_known_route(
            back_asset=self._asset_path("secret_realm_back_button.png")
        )
