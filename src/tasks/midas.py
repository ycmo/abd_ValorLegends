from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult, Roi


class MidasTask(BaseTask):
    spec = TASK_SPECS["midas"]
    required_assets = (
        "task_label.png",
        "midas_title.png",
        "free_button.png",
        "gem_20_button.png",
        "gem_50_button.png",
        "midas_close_button.png",
        "reward_title.png",
    )

    TITLE_ROI: Roi = (360, 45, 250, 70)
    FREE_BUTTON_ROI: Roi = (160, 410, 190, 75)
    GEM_20_BUTTON_ROI: Roi = (370, 410, 190, 75)
    GEM_50_BUTTON_ROI: Roi = (580, 410, 190, 75)
    CLOSE_BUTTON_ROI: Roi = (735, 45, 80, 70)
    REWARD_TITLE_ROI: Roi = (330, 100, 300, 100)
    ACTIVE_BUTTON_THRESHOLD = 0.92
    MAX_ALLOWED_TAPS = 12
    task_scene_anchors = (
        TaskSceneAnchor("midas_title.png", threshold=0.86, roi=TITLE_ROI),
        TaskSceneAnchor("reward_title.png", threshold=0.86, roi=REWARD_TITLE_ROI),
    )

    def execute(self) -> str:
        self._dismiss_reward_overlay_if_present()
        self._require_midas_dialog()
        completed = []
        for _ in range(self.MAX_ALLOWED_TAPS):
            self._dismiss_reward_overlay_if_present()
            tapped = False
            for label, asset_name, roi in self._allowed_buttons():
                if self._tap_if_active(label, asset_name, roi):
                    completed.append(label)
                    tapped = True
                    self._dismiss_reward_overlay_if_present()
                    break
            if not tapped:
                break
        else:
            raise TaskFailedError("Midas exceeded allowed tap limit while exhausting free/20/50 tiers")

        self._close_dialog()
        if not completed:
            return "no active Midas button found; dialog closed"
        return "Midas taps: " + ", ".join(completed)

    def _allowed_buttons(self):
        return (
            ("free", "free_button.png", self.FREE_BUTTON_ROI),
            ("20-gem", "gem_20_button.png", self.GEM_20_BUTTON_ROI),
            ("50-gem", "gem_50_button.png", self.GEM_50_BUTTON_ROI),
        )

    def _tap_if_active(self, label: str, asset_name: str, roi: Roi) -> bool:
        match = self._match_task_asset(
            asset_name,
            roi=roi,
            threshold=self.ACTIVE_BUTTON_THRESHOLD,
            timeout_seconds=1.0,
        )
        if match is None:
            return False
        self.context.controller.tap(*match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)
        return True

    def _dismiss_reward_overlay_if_present(self) -> None:
        if not self._match_task_asset(
            "reward_title.png",
            roi=self.REWARD_TITLE_ROI,
            threshold=0.86,
            timeout_seconds=0.6,
        ):
            return

        self.dismiss_reward_overlay_by_blank_taps(
            is_closed=lambda: self._match_task_asset(
                "reward_title.png",
                roi=self.REWARD_TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            )
            is None,
            max_taps=2,
            failure_message="Midas reward overlay did not close after two blank-area taps",
        )

    def _close_dialog(self) -> None:
        self._dismiss_reward_overlay_if_present()
        self._require_midas_dialog()
        self._tap_task_asset(
            "close Midas dialog",
            "midas_close_button.png",
            roi=self.CLOSE_BUTTON_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        deadline = time.time() + 3.0
        while time.time() <= deadline:
            if not self._match_task_asset(
                "midas_title.png",
                roi=self.TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            ):
                return
        raise TaskFailedError("Midas dialog did not close after tapping close")

    def _require_midas_dialog(self) -> MatchResult:
        return self._require_task_asset(
            "Midas dialog",
            "midas_title.png",
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
            raise TaskFailedError(f"Midas expected screen element not found: {label}")
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
