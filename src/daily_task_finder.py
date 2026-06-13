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
from src.debug_log import DebugLogger
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
    claim_match: Optional[MatchResult] = None
    done_match: Optional[MatchResult] = None
    reason: str = ""


class DailyTaskFinder:
    """Finds a task row in the daily-task list and distinguishes Go vs claimable."""

    DONE_LABEL_THRESHOLD = 0.58
    DONE_BUTTON_THRESHOLD = 0.78

    def __init__(self, controller: DeviceController, matcher: VisionMatcher, logger: Optional[DebugLogger] = None):
        self.controller = controller
        self.matcher = matcher
        self.logger = logger or DebugLogger(False)

    def find_on_current_screen(self, spec: TaskSpec) -> TaskSearchResult:
        label_path = spec.task_label_asset
        if not label_path.exists():
            raise MissingAssetError(f"Missing task label template: {label_path}")
        go_path = self._go_button_path()
        if not go_path.exists():
            raise MissingAssetError(f"Missing shared go button template: {go_path}")

        screen = self.controller.screenshot()
        label_roi = self._task_list_roi(screen_width=screen.shape[1], screen_height=screen.shape[0])
        label = self.matcher.match_any(
            screen,
            self._task_label_candidates(spec),
            threshold=TASK_LABEL_THRESHOLD,
            roi=label_roi,
        )
        if label is None:
            done_result = self._find_done_row(screen, spec, label_roi)
            if done_result is not None:
                return done_result
            return TaskSearchResult(TaskSearchStatus.NOT_FOUND, reason="task label not visible")
        self.logger.log(
            f"daily task label matched task={spec.key} "
            f"template={label.template_path.name} confidence={label.confidence:.3f}"
        )

        go_roi = self._same_row_right_roi(
            screen_width=screen.shape[1],
            screen_height=screen.shape[0],
            label=label,
        )
        go = self._match_go_button(screen, go_roi)
        if go is not None:
            return TaskSearchResult(TaskSearchStatus.READY, label_match=label, go_match=go)

        claim = self._match_claim_button(screen, go_roi)
        if claim is not None:
            return TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                label_match=label,
                claim_match=claim,
                reason="task label found with claim button on the same row",
            )

        done = self._match_done_button(screen, go_roi)
        if done is not None:
            return TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                label_match=label,
                done_match=done,
                reason="task label found with completed button on the same row",
            )

        if self._row_too_close_to_bottom(screen_height=screen.shape[0], label=label):
            return TaskSearchResult(
                TaskSearchStatus.NOT_FOUND,
                label_match=label,
                reason="task row is too close to the bottom edge and Go button was not safely detected",
            )

        return TaskSearchResult(
            TaskSearchStatus.DONE_OR_CLAIMABLE,
            label_match=label,
            reason="task label found but Go button not found on the same row",
        )

    def find_near_current_screen(self, spec: TaskSpec, max_nudge_swipes: int = 2) -> TaskSearchResult:
        """Find a row near the current viewport without resetting the daily list to the top."""
        result = self.find_on_current_screen(spec)
        if result.status != TaskSearchStatus.NOT_FOUND or result.label_match is None:
            return result

        last = result
        for _ in range(max_nudge_swipes):
            if not self._swipe_until_changed(360, 430, 360, 230, duration_ms=320, wait_seconds=0.45):
                return last
            last = self.find_on_current_screen(spec)
            if last.status != TaskSearchStatus.NOT_FOUND:
                return last
            if last.label_match is None:
                return last
        return last

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
                if last.label_match is not None:
                    return last
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
        x = int(screen_width * 0.226)
        y = int(screen_height * 0.391)
        width = int(screen_width * 0.264)
        height = int(screen_height * 0.602)
        return (x, y, width, height)

    @staticmethod
    def _same_row_right_roi(screen_width: int, screen_height: int, label: MatchResult) -> Roi:
        row_h = 100
        row_y = max(0, min(label.center[1] - 35, screen_height - row_h))
        x = int(screen_width * 0.775)
        width = int(screen_width * 0.199)
        return (x, row_y, width, row_h)

    @staticmethod
    def _row_too_close_to_bottom(screen_height: int, label: MatchResult) -> bool:
        return label.center[1] >= screen_height - 70

    def _find_done_row(self, screen, spec: TaskSpec, label_roi: Roi) -> Optional[TaskSearchResult]:
        label = self.matcher.match_any(
            screen,
            self._task_label_candidates(spec),
            threshold=self.DONE_LABEL_THRESHOLD,
            roi=label_roi,
            check_brightness=False,
        )
        if label is None:
            return None

        go_roi = self._same_row_right_roi(
            screen_width=screen.shape[1],
            screen_height=screen.shape[0],
            label=label,
        )
        go = self._match_go_button(screen, go_roi)
        if go is not None:
            self.logger.log(
                f"daily task weak label matched runnable task={spec.key} "
                f"template={label.template_path.name} label_confidence={label.confidence:.3f} "
                f"go_confidence={go.confidence:.3f}"
            )
            return TaskSearchResult(
                TaskSearchStatus.READY,
                label_match=label,
                go_match=go,
                reason="weak task label found with Go button on the same row",
            )

        claim = self._match_claim_button(screen, go_roi)
        if claim is not None:
            self.logger.log(
                f"daily task claim row matched task={spec.key} "
                f"template={label.template_path.name} label_confidence={label.confidence:.3f} "
                f"claim_confidence={claim.confidence:.3f}"
            )
            return TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                label_match=label,
                claim_match=claim,
                reason="weak task label found with claim button on the same row",
            )

        done = self._match_done_button(screen, go_roi)
        if done is None:
            return None

        self.logger.log(
            f"daily task done row matched task={spec.key} "
            f"template={label.template_path.name} label_confidence={label.confidence:.3f} "
            f"done_confidence={done.confidence:.3f}"
        )
        return TaskSearchResult(
            TaskSearchStatus.DONE_OR_CLAIMABLE,
            label_match=label,
            done_match=done,
            reason="weak task label found with completed button on the same row",
        )

    def _match_claim_button(self, screen, roi: Roi) -> Optional[MatchResult]:
        path = SHARED_ASSETS_DIR / "claim_button.png"
        if not path.exists():
            return None
        return self.matcher.match_template(screen, path, threshold=self.DONE_BUTTON_THRESHOLD, roi=roi)

    def _match_done_button(self, screen, roi: Roi) -> Optional[MatchResult]:
        path = SHARED_ASSETS_DIR / "completed_button.png"
        if not path.exists():
            return None
        return self.matcher.match_template(screen, path, threshold=self.DONE_BUTTON_THRESHOLD, roi=roi)

    def _match_go_button(self, screen, roi: Roi) -> Optional[MatchResult]:
        return self.matcher.match_template(screen, self._go_button_path(), threshold=GO_BUTTON_THRESHOLD, roi=roi)

    @staticmethod
    def _go_button_path():
        return SHARED_ASSETS_DIR / "go_button.png"

    @staticmethod
    def _task_label_candidates(spec: TaskSpec) -> tuple:
        paths = [spec.task_label_asset]
        wide_path = spec.asset_dir / "task_label_wide.png"
        if wide_path.exists():
            paths.append(wide_path)
        return tuple(paths)
