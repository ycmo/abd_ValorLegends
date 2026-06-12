from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.ocr_utils import read_texts_easyocr
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
    PAGE_LOAD_TIMEOUT_SECONDS = 45.0
    RESULT_TIMEOUT_SECONDS = 20.0
    FREE_BUTTON_THRESHOLD = 0.80

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None

    def is_task_scene(self, screen) -> bool:
        path = self.asset_path("advanced_contract_label.png")
        if path.exists():
            match = self.context.matcher.match_template(
                screen,
                path,
                threshold=0.78,
                roi=self.PAGE_LABEL_ROI,
            )
            if match is not None:
                return True
        confirm_path = self.asset_path("confirm_button.png")
        if confirm_path.exists():
            match = self.context.matcher.match_template(
                screen,
                confirm_path,
                threshold=0.88,
                roi=self.CONFIRM_BUTTON_ROI,
            )
            if match is not None:
                return True
        return self._screen_ocr_indicates_advanced_contract(screen)

    def execute(self) -> str:
        self._require_summon_page()
        self._tap_task_asset(
            "free summon",
            "free_summon_button.png",
            roi=self.FREE_BUTTON_ROI,
            threshold=self.FREE_BUTTON_THRESHOLD,
            wait_after_seconds=6.0,
        )
        self._tap_task_asset(
            "confirm summon result",
            "confirm_button.png",
            roi=self.CONFIRM_BUTTON_ROI,
            threshold=0.88,
            timeout_seconds=self.RESULT_TIMEOUT_SECONDS,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_post_confirm_reward_if_present()
        self._return_to_daily_tasks()
        return "free summon completed"

    def execute_from_current_scene(self) -> str:
        if self._match_task_asset(
            "confirm_button.png",
            roi=self.CONFIRM_BUTTON_ROI,
            threshold=0.88,
            timeout_seconds=1.0,
        ):
            self._tap_task_asset(
                "confirm summon result",
                "confirm_button.png",
                roi=self.CONFIRM_BUTTON_ROI,
                threshold=0.88,
                timeout_seconds=2.0,
                wait_after_seconds=TRANSITION_WAIT_SECONDS,
            )
            self._dismiss_post_confirm_reward_if_present()
            self._return_to_daily_tasks()
            return "summon result confirmed and returned"

        return self.execute()

    def _dismiss_post_confirm_reward_if_present(self) -> None:
        self.context.controller.tap(80, 500)
        time.sleep(TAP_COOLDOWN_SECONDS)
        self.dismiss_reward_overlay_by_blank_taps(
            is_closed=lambda: self._is_summon_page_visible(timeout_seconds=0.8),
            max_taps=1,
            failure_message="Summon post-confirm reward overlay did not close after two blank-area taps",
        )

    def _return_to_daily_tasks(self) -> None:
        for _ in range(2):
            if not self._is_summon_page_visible(timeout_seconds=2.0):
                break
            self._tap_task_asset(
                "leave summon page",
                "leave_button.png",
                roi=self.LEAVE_BUTTON_ROI,
                threshold=0.82,
                wait_after_seconds=TRANSITION_WAIT_SECONDS,
            )
            if self._is_daily_tasks_visible():
                return

        if self._is_daily_tasks_visible():
            return
        if self.context.navigator.go_to_daily_tasks(max_steps=3):
            return
        raise TaskFailedError("Summon completed, but could not return to Daily Tasks safely")

    def _is_daily_tasks_visible(self) -> bool:
        screen = self.context.controller.screenshot()
        return self.context.detector.detect(screen).scene == Scene.DAILY_TASKS

    def _require_summon_page(self) -> None:
        if not self._is_summon_page_visible(timeout_seconds=self.PAGE_LOAD_TIMEOUT_SECONDS):
            raise TaskFailedError("Summon expected screen element not found: advanced contract summon page")

    def _is_summon_page_visible(self, timeout_seconds: float) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            match = self._match_task_asset(
                "advanced_contract_label.png",
                roi=self.PAGE_LABEL_ROI,
                threshold=0.78,
                timeout_seconds=0.2,
            )
            if match is not None:
                return True
            screen = self.context.controller.screenshot()
            if self._screen_ocr_indicates_advanced_contract(screen):
                return True
            time.sleep(0.5)
        return False

    def _screen_ocr_indicates_advanced_contract(self, screen) -> bool:
        try:
            fragments = read_texts_easyocr(
                screen,
                roi=self.PAGE_LABEL_ROI,
                reader=self._get_ocr_reader(),
                languages=["ch_tra", "en"],
                download_enabled=False,
            )
        except Exception:
            return False

        text = "".join(fragment["text"] for fragment in fragments)
        normalized = "".join(char for char in text if char.isalnum() or "\u4e00" <= char <= "\u9fff")
        return "高" in normalized and "契" in normalized and "約" in normalized

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            from src.ocr_utils import build_easyocr_reader

            self._ocr_reader = build_easyocr_reader(["ch_tra", "en"], download_enabled=False)
        return self._ocr_reader

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
