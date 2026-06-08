from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult, Roi


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
        self._tap_task_asset(
            "set purchase quantity to 2",
            "purchase_quantity_plus_button.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.80,
        )
        self._require_task_asset(
            "purchase quantity 2",
            "purchase_quantity_two.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
        )
        self._tap_task_asset(
            "confirm Lost Forest purchase",
            "purchase_confirm_button.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._wait_for_realm_screen("after purchase")
        self._tap_task_asset(
            "sweep all",
            "sweep_all_button.png",
            roi=self.SWEEP_ALL_ROI,
            threshold=0.82,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_possible_reward_overlay()
        if not self.context.navigator.return_to_daily_tasks_from_known_route(
            back_asset=self.asset_path("secret_realm_back_button.png")
        ):
            raise TaskFailedError("Secret Realm finished, but could not return to Daily Tasks safely")
        return "bought Lost Forest twice and tapped sweep all"

    def _ensure_lost_forest_selected(self) -> None:
        if self._match_task_asset(
            "lost_forest_selected_tab.png",
            roi=self.LEFT_TAB_ROI,
            threshold=0.78,
            timeout_seconds=1.0,
        ):
            return

        tab = self._require_task_asset(
            "Lost Forest tab",
            "lost_forest_tab.png",
            roi=self.LEFT_TAB_ROI,
            threshold=0.78,
        )
        self.context.controller.tap(*tab.center)
        time.sleep(TRANSITION_WAIT_SECONDS)
        self._wait_for_realm_screen("after selecting Lost Forest")

    def _open_purchase_dialog(self) -> None:
        self._tap_task_asset(
            "open purchase dialog",
            "realm_attempt_entry_plus_button.png",
            roi=self.REALM_ATTEMPT_PLUS_ROI,
            threshold=0.78,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._require_task_asset(
            "purchase dialog title",
            "purchase_dialog_title.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
        )

    def _validate_purchase_dialog(self) -> None:
        self._require_task_asset(
            "daily purchase count 5/5",
            "daily_purchase_count_5_5.png",
            roi=self.PURCHASE_DIALOG_ROI,
            threshold=0.82,
        )

    def _wait_for_realm_screen(self, label: str) -> None:
        deadline = time.time() + 5.0
        while time.time() <= deadline:
            if self._match_task_asset(
                "lost_forest_selected_tab.png",
                roi=self.LEFT_TAB_ROI,
                threshold=0.75,
                timeout_seconds=0.5,
            ):
                return
        raise TaskFailedError(f"Lost Forest screen not visible {label}")

    def _dismiss_possible_reward_overlay(self) -> None:
        self.dismiss_reward_overlay_by_blank_taps(max_taps=2)

    def _tap_task_asset(
        self,
        label: str,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        wait_after_seconds: float = TAP_COOLDOWN_SECONDS,
    ) -> MatchResult:
        match = self._require_task_asset(label, asset_name, roi=roi, threshold=threshold)
        self.context.controller.tap(*match.center)
        time.sleep(wait_after_seconds)
        return match

    def _require_task_asset(
        self,
        label: str,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
    ) -> MatchResult:
        match = self._match_task_asset(asset_name, roi=roi, threshold=threshold, timeout_seconds=timeout_seconds)
        if match is None:
            raise TaskFailedError(f"Secret Realm expected screen element not found: {label}")
        return match

    def _match_task_asset(
        self,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
    ) -> Optional[MatchResult]:
        path = self.asset_path(asset_name)
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(screen, path, threshold=threshold, roi=roi)
            if match is not None:
                return match
            time.sleep(0.35)
        return None
