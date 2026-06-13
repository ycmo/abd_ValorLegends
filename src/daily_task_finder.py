from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

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
    weak_match: bool = False
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
                self._save_search_debug(screen, spec, label_roi, done_result)
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

        done_status, done_status_kind = self._match_done_status_button(screen, go_roi)
        if done_status is not None:
            result = TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                label_match=label,
                claim_match=done_status if done_status_kind == "claim" else None,
                done_match=done_status if done_status_kind == "completed" else None,
                reason="task label found with done status button on the same row",
            )
            self._save_search_debug(screen, spec, label_roi, result)
            return result

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
        weak_done_candidate: Optional[TaskSearchResult] = None
        for attempt in range(max_swipes + 1):
            last = self.find_on_current_screen(spec)
            if last.status != TaskSearchStatus.NOT_FOUND:
                if last.status == TaskSearchStatus.DONE_OR_CLAIMABLE and last.weak_match:
                    weak_done_candidate = weak_done_candidate or last
                else:
                    return last
            if attempt >= max_swipes:
                break
            if not self._swipe_until_changed(360, 430, 360, 230, duration_ms=420, wait_seconds=TAP_COOLDOWN_SECONDS):
                if weak_done_candidate is not None:
                    return weak_done_candidate
                if last.label_match is not None:
                    return last
                return TaskSearchResult(TaskSearchStatus.NOT_FOUND, reason="task label not visible before list bottom")
        return weak_done_candidate or last

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

        status_roi = self._same_row_right_roi(
            screen_width=screen.shape[1],
            screen_height=screen.shape[0],
            label=label,
        )
        done_status, done_status_kind = self._match_done_status_button(screen, status_roi)
        if done_status is not None:
            self.logger.log(
                f"daily task done status row matched task={spec.key} "
                f"template={label.template_path.name} label_confidence={label.confidence:.3f} "
                f"status_template={done_status.template_path.name} status_confidence={done_status.confidence:.3f}"
            )
            return TaskSearchResult(
                TaskSearchStatus.DONE_OR_CLAIMABLE,
                label_match=label,
                claim_match=done_status if done_status_kind == "claim" else None,
                done_match=done_status if done_status_kind == "completed" else None,
                weak_match=True,
                reason="weak task label found with done status button on the same row",
            )

        return None

    def _match_done_status_button(self, screen, roi: Roi) -> Tuple[Optional[MatchResult], str]:
        claim = self._match_claim_button(screen, roi)
        completed = self._match_done_button(screen, roi)
        candidates = [
            (claim, "claim"),
            (completed, "completed"),
        ]
        matches = [(match, kind) for match, kind in candidates if match is not None]
        if not matches:
            return None, ""
        return max(matches, key=lambda item: item[0].confidence)

    def _save_search_debug(self, screen, spec: TaskSpec, label_roi: Roi, result: TaskSearchResult) -> None:
        save_debug = getattr(self.controller, "save_annotated_debug", None)
        if save_debug is None:
            return

        boxes = [(*label_roi, "label_roi")]
        lines = [
            f"daily search: {spec.key} {spec.display_name}",
            f"status={result.status.value} weak={result.weak_match}",
        ]
        if result.label_match is not None:
            label = result.label_match
            status_roi = self._same_row_right_roi(screen.shape[1], screen.shape[0], label)
            boxes.append((*label.bbox, "label"))
            boxes.append((*status_roi, "status_roi"))
            lines.append(f"label {label.template_path.name} conf={label.confidence:.3f} center={label.center}")
        if result.go_match is not None:
            boxes.append((*result.go_match.bbox, "go"))
            lines.append(f"go conf={result.go_match.confidence:.3f} center={result.go_match.center}")
        status_match = result.claim_match or result.done_match
        if status_match is not None:
            boxes.append((*status_match.bbox, "done_status"))
            lines.append(
                f"done_status {status_match.template_path.name} "
                f"conf={status_match.confidence:.3f} center={status_match.center}"
            )
        if result.reason:
            lines.append(result.reason)
        save_debug(f"daily_task_{spec.key}_{result.status.value}", screen, lines=lines, boxes=boxes)

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
