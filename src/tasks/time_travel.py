from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.ocr_utils import build_easyocr_reader
from src.task_runner import BaseTask, TaskSceneAnchor
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
    COST_OCR_ROI: Roi = (665, 395, 170, 55)
    COST_BUTTON_THRESHOLD = 0.96
    MAX_50_GEM_TAPS = 6
    task_scene_anchors = (
        TaskSceneAnchor("time_travel_title.png", threshold=0.86, roi=TITLE_ROI),
        TaskSceneAnchor("reward_title.png", threshold=0.86, roi=REWARD_TITLE_ROI),
    )

    def __init__(self, context):
        super().__init__(context)
        self._cost_ocr_reader = None

    def execute(self) -> str:
        return self.execute_from_current_scene()

    def execute_from_current_scene(self) -> str:
        self._dismiss_reward_overlay_if_present()
        self._require_time_travel_dialog()
        free_used = self._tap_free_if_visible()
        if free_used:
            self._dismiss_reward_overlay_if_present()
        self._require_time_travel_dialog()
        gem_50_count = self._tap_all_gem_50()
        self._close_dialog_if_visible()

        parts = []
        if free_used:
            parts.append("free")
        parts.append(f"{gem_50_count}x 50-gem")
        return "time travel completed: " + ", ".join(parts)

    def _tap_free_if_visible(self) -> bool:
        match = self._match_task_asset(
            "free_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=0.88,
            timeout_seconds=0.8,
        )
        if match is None:
            return False
        self.context.controller.tap(*match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)
        return True

    def _tap_all_gem_50(self) -> int:
        count = 0
        for _ in range(self.MAX_50_GEM_TAPS):
            screen = self.context.controller.screenshot()
            if not self._is_time_travel_dialog_screen(screen):
                if count > 0:
                    return count
                raise TaskFailedError("Time Travel dialog is not visible before checking gem tier")

            cost = self._detect_action_cost(screen)
            if cost == 100:
                return count
            if cost != 50:
                raise TaskFailedError(f"Time Travel expected 50 or 100 gem tier, but detected cost={cost!r}")

            self._tap_gem_50(detected_cost=cost)
            count += 1
            self._dismiss_reward_overlay_if_present()

        raise TaskFailedError(
            f"Time Travel exceeded {self.MAX_50_GEM_TAPS} consecutive 50-gem taps; stopping before loop"
        )

    def _tap_gem_50(self, detected_cost: Optional[int] = None) -> None:
        cost = self._detect_action_cost() if detected_cost is None else detected_cost
        if cost == 100:
            raise TaskFailedError("Time Travel is already at 100-gem tier; stopping before paid 100-gem action")
        if cost != 50:
            raise TaskFailedError(f"Time Travel expected 50-gem tier before tapping, but detected cost={cost!r}")
        self._tap_task_asset(
            "50-gem time travel",
            "gem_50_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=self.COST_BUTTON_THRESHOLD,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _detect_action_cost(self, screen=None) -> Optional[int]:
        if screen is None:
            screen = self.context.controller.screenshot()
        cost = self._read_action_cost_ocr(screen)
        if cost in (50, 100):
            return cost

        if self.context.matcher.match_template(
            screen,
            self.asset_path("gem_100_button.png"),
            threshold=self.COST_BUTTON_THRESHOLD,
            roi=self.ACTION_BUTTON_ROI,
        ):
            return 100
        if self.context.matcher.match_template(
            screen,
            self.asset_path("gem_50_button.png"),
            threshold=self.COST_BUTTON_THRESHOLD,
            roi=self.ACTION_BUTTON_ROI,
        ):
            return 50
        return cost

    def _is_time_travel_dialog_screen(self, screen) -> bool:
        return (
            self.context.matcher.match_template(
                screen,
                self.asset_path("time_travel_title.png"),
                threshold=0.86,
                roi=self.TITLE_ROI,
            )
            is not None
        )

    def _read_action_cost_ocr(self, screen) -> Optional[int]:
        x, y, w, h = self.COST_OCR_ROI
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return None
        try:
            ocr_results = self._get_cost_ocr_reader().readtext(
                crop,
                detail=1,
                allowlist="0123456789",
            )
        except Exception:
            return None

        pieces = []
        for box, text, confidence in ocr_results:
            digits = "".join(char for char in str(text) if char.isdigit())
            if not digits:
                continue
            xs = []
            for point in box:
                try:
                    xs.append(float(point[0]))
                except (TypeError, ValueError, IndexError):
                    continue
            left = min(xs) if xs else 0.0
            pieces.append((left, digits, float(confidence)))
        if not pieces:
            return None
        pieces.sort(key=lambda item: item[0])
        text = "".join(piece[1] for piece in pieces)
        try:
            return int(text)
        except ValueError:
            return None

    def _get_cost_ocr_reader(self):
        if self._cost_ocr_reader is None:
            self._cost_ocr_reader = build_easyocr_reader(["en"], download_enabled=False)
        return self._cost_ocr_reader

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

        self.dismiss_reward_overlay_by_blank_taps(
            is_closed=lambda: self._match_task_asset(
                "reward_title.png",
                roi=self.REWARD_TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            )
            is None,
            max_taps=2,
            failure_message="Time Travel reward overlay did not close after two blank-area taps",
        )

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

    def _close_dialog_if_visible(self) -> None:
        screen = self.context.controller.screenshot()
        if self._is_time_travel_dialog_screen(screen):
            self._close_dialog()

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
