from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.task_runner import BaseTask
from src.vision_matcher import MatchResult, Roi


class TimeTravelTask(BaseTask):
    spec = TASK_SPECS["time_travel"]
    required_assets = (
        "task_label.png",
        "time_travel_title.png",
        "free_button.png",
        "gem_50_button.png",
        "gem_100_button.png",
        "cancel_button.png",
        "reward_title.png",
    )

    TITLE_ROI: Roi = (430, 70, 470, 130)
    ACTION_BUTTON_ROI: Roi = (640, 380, 220, 80)
    CANCEL_BUTTON_ROI: Roi = (480, 380, 190, 80)
    REWARD_TITLE_ROI: Roi = (300, 90, 380, 120)
    COST_BUTTON_THRESHOLD = 0.96

    def execute(self) -> str:
        self._require_time_travel_dialog()
        self._tap_task_asset(
            "free time travel",
            "free_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=0.88,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_reward_overlay_if_present()
        self._require_time_travel_dialog()
        self._tap_gem_50()
        self._dismiss_reward_overlay_if_present()
        self._close_dialog()
        return "free and 50-gem time travel completed"

    def _tap_gem_50(self) -> None:
        if self._match_task_asset(
            "gem_100_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=self.COST_BUTTON_THRESHOLD,
            timeout_seconds=1.0,
        ):
            raise TaskFailedError("Time Travel is already at 100-gem tier; stopping before paid 100-gem action")
        self._tap_task_asset(
            "50-gem time travel",
            "gem_50_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=self.COST_BUTTON_THRESHOLD,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _dismiss_reward_overlay_if_present(self) -> None:
        deadline = time.time() + 4.0
        while time.time() <= deadline:
            if self._match_task_asset(
                "reward_title.png",
                roi=self.REWARD_TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            ):
                break
            if self._match_task_asset(
                "time_travel_title.png",
                roi=self.TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            ):
                return
        else:
            return

        for _ in range(2):
            self.context.controller.tap(80, 500)
            time.sleep(TAP_COOLDOWN_SECONDS)
            if not self._match_task_asset(
                "reward_title.png",
                roi=self.REWARD_TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            ):
                return
        raise TaskFailedError("Time Travel reward overlay did not close after two blank-area taps")

    def _close_dialog(self) -> None:
        self._require_time_travel_dialog()
        self._tap_task_asset(
            "close time travel dialog",
            "cancel_button.png",
            roi=self.CANCEL_BUTTON_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        deadline = time.time() + 3.0
        while time.time() <= deadline:
            if not self._match_task_asset(
                "time_travel_title.png",
                roi=self.TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            ):
                return
        raise TaskFailedError("Time Travel dialog did not close after tapping cancel")

    def _require_time_travel_dialog(self) -> MatchResult:
        return self._require_task_asset(
            "time travel dialog",
            "time_travel_title.png",
            roi=self.TITLE_ROI,
            threshold=0.86,
        )

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
            raise TaskFailedError(f"Time Travel expected screen element not found: {label}")
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
