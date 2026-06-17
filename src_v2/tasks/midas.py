"""
midas.py — Midas (Phase 2)
"""
from __future__ import annotations

import time
from typing import Optional

from src.config import SHARED_ASSETS_DIR, TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src_v2.task_runner import BaseTask, TaskRunResult, TaskState, TaskSceneAnchor
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
    BUSY_OVERLAY_ROI: Roi = (400, 180, 180, 180)
    
    BUSY_OVERLAY_THRESHOLD = 0.86
    BUSY_WAIT_MAX_SECONDS = 90.0
    ACTIVE_BUTTON_THRESHOLD = 0.92
    MAX_ALLOWED_TAPS = 12

    task_scene_anchors = (
        TaskSceneAnchor("midas_title.png", threshold=0.86, roi=TITLE_ROI),
        TaskSceneAnchor("reward_title.png", threshold=0.86, roi=REWARD_TITLE_ROI),
    )

    def _execute_and_return(self, started: float) -> TaskRunResult:
        # NOTE: return_to_daily_tasks() is intentionally skipped for MidasTask.
        # Calling navigator.return_to_daily_tasks() after closing the Midas dialog
        # can stall or mis-size the next screen.
        try:
            result = self.execute_from_current_scene()
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except BotError as exc:
            return self._result(TaskState.FAILED, str(exc), started)
        return self._result(TaskState.COMPLETED, result or "completed", started)

    def execute(self) -> str:
        self._require_midas_dialog()

        try:
            for _ in range(self.MAX_ALLOWED_TAPS):
                acted = False
                if self._tap_if_active("free_button.png", self.FREE_BUTTON_ROI):
                    self._dismiss_reward_overlay_if_present()
                    acted = True
                elif self._tap_if_active("gem_20_button.png", self.GEM_20_BUTTON_ROI):
                    self._dismiss_reward_overlay_if_present()
                    acted = True
                elif self._tap_if_active("gem_50_button.png", self.GEM_50_BUTTON_ROI):
                    self._dismiss_reward_overlay_if_present()
                    acted = True
                
                if not acted:
                    break
        except BotError as exc:
            self._log(f"Midas error during tap loop: {exc}")
            self._tap_close_until_gone()
            raise

        self._tap_close_until_gone()
        return "midas taps completed"


    def _require_midas_dialog(self) -> None:
        if self._wait_for_midas("midas_title.png", roi=self.TITLE_ROI, threshold=0.86, timeout_seconds=3.0) is None:
            raise TaskFailedError("Midas dialog title not found")

    def _tap_if_active(self, asset_name: str, roi: Roi) -> bool:
        match = self._wait_for_midas(
            asset_name,
            roi=roi,
            threshold=self.ACTIVE_BUTTON_THRESHOLD,
            timeout_seconds=1.0,
        )
        if match is None:
            return False
        self.context.controller.tap(*match.center)
        time.sleep(TAP_COOLDOWN_SECONDS)
        return True

    def _dismiss_reward_overlay_if_present(self) -> None:
        if self._wait_for_midas(
            "reward_title.png", roi=self.REWARD_TITLE_ROI, threshold=0.86, timeout_seconds=0.6
        ) is not None:
            self._dismiss_overlay_by_blank_taps(
                is_closed=lambda: self._wait_for_midas(
                    "reward_title.png", roi=self.REWARD_TITLE_ROI, threshold=0.86, timeout_seconds=0.4
                ) is None,
                max_taps=2,
            )

    def _tap_close_until_gone(self) -> None:
        for _ in range(5):
            match = self._wait_for_midas(
                "midas_close_button.png", roi=self.CLOSE_BUTTON_ROI, threshold=0.86, timeout_seconds=0.6
            )
            if match is None:
                return  # 已關閉
            self.context.controller.tap(*match.center)
            time.sleep(TAP_COOLDOWN_SECONDS)
            if self._wait_for_midas(
                "midas_close_button.png", roi=self.CLOSE_BUTTON_ROI, threshold=0.86, timeout_seconds=0.6
            ) is None:
                return

    def _wait_for_midas(
        self,
        asset_name: str,
        *,
        roi=None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
        poll_interval: float = 0.35,
    ) -> Optional[MatchResult]:
        path = self._asset_path(asset_name)
        deadline = time.time() + timeout_seconds
        busy_waited = 0.0
        busy_logged = False
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            if self._is_busy_overlay(screen):
                if not busy_logged:
                    self._log("Midas: busy overlay detected, waiting...")
                    busy_logged = True
                time.sleep(1.5)
                if busy_waited < self.BUSY_WAIT_MAX_SECONDS:
                    deadline += 1.5
                    busy_waited += 1.5
                continue
            if busy_logged:
                self._log("Midas: busy overlay cleared")
                busy_logged = False
            match = self.context.matcher.match_template(
                screen, path, threshold=threshold, roi=roi
            )
            if match is not None:
                return match
            time.sleep(poll_interval)
        return None

    def _is_busy_overlay(self, screen) -> bool:
        path = SHARED_ASSETS_DIR / "busy_waiting_overlay.png"
        if not path.exists():
            return False
        return self.context.matcher.match_template(
            screen, path,
            threshold=self.BUSY_OVERLAY_THRESHOLD,
            roi=self.BUSY_OVERLAY_ROI,
            check_brightness=False,
        ) is not None
