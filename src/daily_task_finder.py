from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import cv2
import numpy as np

from src.adb_controller import DeviceController
from src.config import (
    GO_BUTTON_THRESHOLD,
    SHARED_ASSETS_DIR,
    TASK_LABEL_THRESHOLD,
    TAP_COOLDOWN_SECONDS,
    TaskSpec,
)
from src.exceptions import MissingAssetError
from src.vision_matcher import MatchResult, Roi, VisionMatcher


class TaskSearchStatus(str, Enum):
    READY = "ready"
    DONE_OR_CLAIMABLE = "done_or_claimable"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class TaskSearchResult:
    status: TaskSearchStatus
    label_match: Optional[MatchResult] = None
    go_match: Optional[MatchResult] = None
    reason: str = ""


class DailyTaskFinder:
    """Finds a task row in the daily-task list and distinguishes Go vs claimable."""

    def __init__(self, controller: DeviceController, matcher: VisionMatcher):
        self.controller = controller
        self.matcher = matcher

    def find_on_current_screen(self, spec: TaskSpec) -> TaskSearchResult:
        label_path = spec.task_label_asset
        go_path = SHARED_ASSETS_DIR / "go_button.png"
        if not label_path.exists():
            raise MissingAssetError(f"Missing task label template: {label_path}")
        if not go_path.exists():
            raise MissingAssetError(f"Missing shared go button template: {go_path}")

        screen = self.controller.screenshot()
        label_roi = self._task_list_roi(screen_width=screen.shape[1], screen_height=screen.shape[0])
        label = self.matcher.match_template(
            screen,
            label_path,
            threshold=TASK_LABEL_THRESHOLD,
            roi=label_roi,
        )
        if label is None:
            return TaskSearchResult(TaskSearchStatus.NOT_FOUND, reason="task label not visible")

        go_roi = self._same_row_right_roi(screen_width=screen.shape[1], label=label)
        go = self.matcher.match_template(screen, go_path, threshold=GO_BUTTON_THRESHOLD, roi=go_roi)
        if go is None:
            return TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                label_match=label,
                reason="task label found but Go button not found on the same row",
            )
        return TaskSearchResult(TaskSearchStatus.READY, label_match=label, go_match=go)

    def scroll_to_task(
        self,
        spec: TaskSpec,
        max_swipes: int = 6,
        reset_to_top_swipes: int = 5,
    ) -> TaskSearchResult:
        self._scroll_to_top(reset_to_top_swipes)
        last = TaskSearchResult(TaskSearchStatus.NOT_FOUND, reason="not searched yet")
        for attempt in range(max_swipes + 1):
            last = self.find_on_current_screen(spec)
            if last.status != TaskSearchStatus.NOT_FOUND:
                return last
            if attempt >= max_swipes:
                break
            if not self._swipe_until_changed(360, 430, 360, 230, duration_ms=420, wait_seconds=TAP_COOLDOWN_SECONDS):
                return TaskSearchResult(TaskSearchStatus.NOT_FOUND, reason="task label not visible before list bottom")
        return last

    def _scroll_to_top(self, swipes: int) -> None:
        for _ in range(swipes):
            if not self._swipe_until_changed(360, 230, 360, 430, duration_ms=350, wait_seconds=0.35):
                return

    def _swipe_until_changed(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        duration_ms: int,
        wait_seconds: float,
    ) -> bool:
        before = self.controller.screenshot()
        before_fp = self._list_fingerprint(before)
        self.controller.swipe(x1, y1, x2, y2, duration_ms=duration_ms)
        time.sleep(wait_seconds)
        after = self.controller.screenshot()
        after_fp = self._list_fingerprint(after)
        return self._fingerprints_differ(before_fp, after_fp)

    @staticmethod
    def _list_fingerprint(screen) -> np.ndarray:
        height, width = screen.shape[:2]
        x1 = int(width * 0.14)
        x2 = int(width * 0.97)
        y1 = int(height * 0.34)
        y2 = int(height * 0.96)
        crop = screen[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (96, 48), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _fingerprints_differ(before: np.ndarray, after: np.ndarray) -> bool:
        diff = cv2.absdiff(before, after)
        return float(np.mean(diff)) >= 1.5

    @staticmethod
    def _task_list_roi(screen_width: int, screen_height: int) -> Roi:
        x = int(screen_width * 0.15)
        y = int(screen_height * 0.36)
        return (x, y, screen_width - x, screen_height - y)

    @staticmethod
    def _same_row_right_roi(screen_width: int, label: MatchResult) -> Roi:
        row_y = max(0, label.center[1] - 50)
        row_h = 100
        x = int(screen_width * 0.70)
        return (x, row_y, screen_width - x, row_h)
