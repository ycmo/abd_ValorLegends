"""
time_travel.py — Time Travel (Phase 2)
"""
from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.ocr_utils import get_cached_easyocr_reader
from src_v2.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import Roi


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
        self._dismiss_reward_overlay_if_present()
        self._require(
            "time travel dialog",
            "time_travel_title.png",
            roi=self.TITLE_ROI,
            threshold=0.86,
        )
        
        free_used = False
        if self._wait_for(
            "free_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=0.88,
            timeout_seconds=0.8,
        ) is not None:
            self._tap(
                "free", 
                "free_button.png", 
                roi=self.ACTION_BUTTON_ROI, 
                threshold=0.88, 
                wait_after=TRANSITION_WAIT_SECONDS
            )
            free_used = True
            self._dismiss_reward_overlay_if_present()
            
        self._require(
            "time travel dialog",
            "time_travel_title.png",
            roi=self.TITLE_ROI,
            threshold=0.86,
        )
        gem_50_count = self._tap_all_gem_50()
        self._close_dialog_if_visible()

        parts = []
        if free_used:
            parts.append("free")
        parts.append(f"{gem_50_count}x 50-gem")
        return "time travel completed: " + ", ".join(parts)

    def _tap_all_gem_50(self) -> int:
        count = 0
        for _ in range(self.MAX_50_GEM_TAPS):
            screen = self.context.controller.screenshot()
            if self._wait_for("time_travel_title.png", roi=self.TITLE_ROI, threshold=0.86, timeout_seconds=0.1) is None:
                if count > 0:
                    return count
                raise TaskFailedError("Time Travel dialog is not visible before checking gem tier")

            cost = self._detect_action_cost(screen)
            if cost == 100:
                return count
            if cost != 50:
                raise TaskFailedError(f"Time Travel expected 50 or 100 gem tier, but detected cost={cost!r}")

            self._tap(
                "50-gem time travel",
                "gem_50_button.png",
                roi=self.ACTION_BUTTON_ROI,
                threshold=self.COST_BUTTON_THRESHOLD,
                wait_after=TRANSITION_WAIT_SECONDS,
            )
            count += 1
            self._dismiss_reward_overlay_if_present()

        raise TaskFailedError(
            f"Time Travel exceeded {self.MAX_50_GEM_TAPS} consecutive 50-gem taps; stopping before loop"
        )

    def _detect_action_cost(self, screen=None) -> Optional[int]:
        if screen is None:
            screen = self.context.controller.screenshot()
        cost = self._read_action_cost_ocr(screen)
        if cost in (50, 100):
            return cost

        if self.context.matcher.match_template(
            screen,
            self._asset_path("gem_100_button.png"),
            threshold=self.COST_BUTTON_THRESHOLD,
            roi=self.ACTION_BUTTON_ROI,
        ):
            return 100
        if self.context.matcher.match_template(
            screen,
            self._asset_path("gem_50_button.png"),
            threshold=self.COST_BUTTON_THRESHOLD,
            roi=self.ACTION_BUTTON_ROI,
        ):
            return 50
        return cost

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
            self._cost_ocr_reader = get_cached_easyocr_reader(("en",), download_enabled=False)
        return self._cost_ocr_reader

    def _dismiss_reward_overlay_if_present(self) -> None:
        if self._wait_for("reward_title.png", roi=self.REWARD_TITLE_ROI, threshold=0.86, timeout_seconds=4.0) is not None:
            self._dismiss_overlay_by_blank_taps(
                is_closed=lambda: self._wait_for(
                    "reward_title.png", roi=self.REWARD_TITLE_ROI,
                    threshold=0.86, timeout_seconds=0.4,
                ) is None,
                max_taps=2,
            )

    def _close_dialog_if_visible(self) -> None:
        if self._wait_for("time_travel_title.png", roi=self.TITLE_ROI, threshold=0.86, timeout_seconds=0.5) is not None:
            self._tap("cancel", "cancel_button.png", roi=self.CANCEL_BUTTON_ROI,
                      threshold=0.86, wait_after=TRANSITION_WAIT_SECONDS)
            if self._wait_for("time_travel_title.png", roi=self.TITLE_ROI,
                              threshold=0.86, timeout_seconds=3.0) is not None:
                raise TaskFailedError("Time Travel dialog did not close after cancel")
