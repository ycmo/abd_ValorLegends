"""
summon.py — Summon (Phase 2)
"""
from __future__ import annotations

import time

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src_v2.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import Roi


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
    PAGE_LOAD_TIMEOUT_SECONDS = 45.0
    RESULT_TIMEOUT_SECONDS = 20.0
    FREE_BUTTON_THRESHOLD = 0.80

    task_scene_anchors = (
        TaskSceneAnchor("advanced_contract_label.png", threshold=0.78, roi=PAGE_LABEL_ROI),
        TaskSceneAnchor("confirm_button.png", threshold=0.88, roi=CONFIRM_BUTTON_ROI),
    )

    def execute(self) -> str:
        self._require_summon_page()
        self._tap(
            "free summon",
            "free_summon_button.png",
            roi=self.FREE_BUTTON_ROI,
            threshold=self.FREE_BUTTON_THRESHOLD,
            wait_after=6.0,
        )
        self._tap(
            "confirm summon result",
            "confirm_button.png",
            roi=self.CONFIRM_BUTTON_ROI,
            threshold=0.88,
            timeout_seconds=self.RESULT_TIMEOUT_SECONDS,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_post_confirm_reward_if_present()
        return "free summon completed"

    def execute_from_current_scene(self) -> str:
        if self._wait_for(
            "confirm_button.png",
            roi=self.CONFIRM_BUTTON_ROI,
            threshold=0.88,
            timeout_seconds=1.0,
        ) is not None:
            self._tap(
                "confirm summon result",
                "confirm_button.png",
                roi=self.CONFIRM_BUTTON_ROI,
                threshold=0.88,
                timeout_seconds=2.0,
                wait_after=TRANSITION_WAIT_SECONDS,
            )
            self._dismiss_post_confirm_reward_if_present()
            return "summon result confirmed and returned"
            
        return self.execute()

    def _pre_return_hook(self) -> None:
        if self._is_summon_page_visible(timeout_seconds=2.0):
            self._tap(
                "leave summon page", 
                "leave_button.png",
                roi=self.LEAVE_BUTTON_ROI, 
                threshold=0.82,
                wait_after=TRANSITION_WAIT_SECONDS,
            )

    def _require_summon_page(self) -> None:
        if not self._is_summon_page_visible(timeout_seconds=self.PAGE_LOAD_TIMEOUT_SECONDS):
            raise TaskFailedError("Advanced Contract summon page not visible")

    def _is_summon_page_visible(self, timeout_seconds: float) -> bool:
        return (
            self._wait_for("advanced_contract_label.png", roi=self.PAGE_LABEL_ROI,
                           threshold=0.78, timeout_seconds=timeout_seconds) is not None
            or self._wait_for("confirm_button.png", roi=self.CONFIRM_BUTTON_ROI,
                              threshold=0.88, timeout_seconds=0.5) is not None
        )

    def _dismiss_post_confirm_reward_if_present(self) -> None:
        self.context.controller.tap(80, 500)
        time.sleep(TAP_COOLDOWN_SECONDS)
        self._dismiss_overlay_by_blank_taps(
            is_closed=lambda: self._is_summon_page_visible(timeout_seconds=0.8),
            max_taps=1,
        )
