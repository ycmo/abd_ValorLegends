from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.scene_detector import Scene
from src.task_runner import BaseTask
from src.vision_matcher import MatchResult, Roi


class SummonTask(BaseTask):
    spec = TASK_SPECS["summon"]
    required_assets = (
        "task_label.png",
        "advanced_contract_label.png",
        "free_summon_button.png",
        "confirm_button.png",
        "leave_button.png",
    )

    PAGE_LABEL_ROI: Roi = (70, 330, 160, 70)
    FREE_BUTTON_ROI: Roi = (30, 380, 230, 90)
    CONFIRM_BUTTON_ROI: Roi = (500, 420, 230, 80)
    LEAVE_BUTTON_ROI: Roi = (0, 0, 110, 90)

    def execute(self) -> str:
        self._require_summon_page()
        self._tap_task_asset(
            "free summon",
            "free_summon_button.png",
            roi=self.FREE_BUTTON_ROI,
            threshold=0.88,
            wait_after_seconds=6.0,
        )
        self._tap_task_asset(
            "confirm summon result",
            "confirm_button.png",
            roi=self.CONFIRM_BUTTON_ROI,
            threshold=0.88,
            timeout_seconds=12.0,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_post_confirm_reward_if_present()
        self._return_to_daily_tasks()
        return "free summon completed"

    def _dismiss_post_confirm_reward_if_present(self) -> None:
        for _ in range(2):
            if self._match_task_asset(
                "advanced_contract_label.png",
                roi=self.PAGE_LABEL_ROI,
                threshold=0.78,
                timeout_seconds=0.8,
            ):
                return
            self.context.controller.tap(80, 500)
            time.sleep(TAP_COOLDOWN_SECONDS)
        if not self._match_task_asset(
            "advanced_contract_label.png",
            roi=self.PAGE_LABEL_ROI,
            threshold=0.78,
            timeout_seconds=1.0,
        ):
            raise TaskFailedError("Summon post-confirm reward overlay did not close after two blank-area taps")

    def _return_to_daily_tasks(self) -> None:
        if self._match_task_asset(
            "advanced_contract_label.png",
            roi=self.PAGE_LABEL_ROI,
            threshold=0.78,
            timeout_seconds=4.0,
        ):
            self._tap_task_asset(
                "leave summon page",
                "leave_button.png",
                roi=self.LEAVE_BUTTON_ROI,
                threshold=0.82,
                wait_after_seconds=TRANSITION_WAIT_SECONDS,
            )

        if self._is_daily_tasks_visible():
            return
        if self.context.navigator.go_to_daily_tasks(max_steps=3):
            return
        raise TaskFailedError("Summon completed, but could not return to Daily Tasks safely")

    def _is_daily_tasks_visible(self) -> bool:
        screen = self.context.controller.screenshot()
        return self.context.detector.detect(screen).scene == Scene.DAILY_TASKS

    def _require_summon_page(self) -> MatchResult:
        return self._require_task_asset(
            "advanced contract summon page",
            "advanced_contract_label.png",
            roi=self.PAGE_LABEL_ROI,
            threshold=0.78,
            timeout_seconds=8.0,
        )

    def _tap_task_asset(
        self,
        label: str,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
        wait_after_seconds: float = TAP_COOLDOWN_SECONDS,
    ) -> MatchResult:
        match = self._require_task_asset(
            label,
            asset_name,
            roi=roi,
            threshold=threshold,
            timeout_seconds=timeout_seconds,
        )
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
            raise TaskFailedError(f"Summon expected screen element not found: {label}")
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
