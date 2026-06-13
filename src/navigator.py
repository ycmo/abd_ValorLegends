from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from src.adb_controller import DeviceController
from src.config import SHARED_ASSETS_DIR, TRANSITION_WAIT_SECONDS, TaskSpec
from src.daily_task_finder import DailyTaskFinder, TaskSearchResult, TaskSearchStatus
from src.debug_log import DebugLogger
from src.exceptions import MissingAssetError, NavigationError
from src.scene_detector import Scene, SceneDetector
from src.vision_matcher import VisionMatcher


class OpenTaskStatus(str, Enum):
    OPENED = "opened"
    SKIPPED_DONE_OR_CLAIMABLE = "skipped_done_or_claimable"


@dataclass(frozen=True)
class OpenTaskResult:
    status: OpenTaskStatus
    reason: str = ""


class Navigator:
    """Scene navigation shared by all task runners."""

    DAILY_ENTRY_ROI = (840, 0, 120, 120)

    def __init__(
        self,
        controller: DeviceController,
        matcher: VisionMatcher,
        detector: SceneDetector,
        finder: DailyTaskFinder,
        logger: Optional[DebugLogger] = None,
    ):
        self.controller = controller
        self.matcher = matcher
        self.detector = detector
        self.finder = finder
        self.logger = logger or DebugLogger(False)

    def go_to_daily_tasks(self, max_steps: int = 6) -> bool:
        for step in range(max_steps):
            screen = self.controller.screenshot()
            detected = self.detector.detect(screen)
            self.logger.log(f"go_to_daily_tasks step={step + 1}/{max_steps} scene={detected.scene.value}")
            if detected.scene == Scene.DAILY_TASKS:
                return True

            entry = self._match_daily_tasks_entry(screen)
            if entry is not None:
                self.controller.tap(*entry.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                continue

            if detected.scene == Scene.MAIN:
                if not self._daily_tasks_entry_assets():
                    raise MissingAssetError(
                        f"Main screen detected but daily task entry template is missing: {SHARED_ASSETS_DIR}"
                    )
                raise NavigationError("Main screen detected but daily task entry was not found")

            return False
        return False

    def open_task_from_daily(self, spec: TaskSpec) -> OpenTaskResult:
        if not self.go_to_daily_tasks():
            raise NavigationError("Cannot reach daily tasks before opening task")

        result = self.finder.find_near_current_screen(spec)
        if result.status == TaskSearchStatus.NOT_FOUND:
            result = self.finder.scroll_to_task(spec)

        if result.status == TaskSearchStatus.DONE_OR_CLAIMABLE:
            return OpenTaskResult(
                OpenTaskStatus.SKIPPED_DONE_OR_CLAIMABLE,
                reason=result.reason,
            )
        if result.status != TaskSearchStatus.READY or result.go_match is None:
            raise NavigationError(f"Cannot find runnable task row for {spec.display_name}: {result.reason}")

        self._annotate_daily_task_tap(spec, result)
        self.controller.tap(*result.go_match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)
        return OpenTaskResult(OpenTaskStatus.OPENED)

    def open_task_from_current_daily_screen(self, spec: TaskSpec) -> OpenTaskResult:
        screen = self.controller.screenshot()
        detected = self.detector.detect(screen)
        if detected.scene != Scene.DAILY_TASKS:
            raise NavigationError("Current screen is not Daily Tasks")

        result = self.finder.find_near_current_screen(spec)
        if result.status == TaskSearchStatus.DONE_OR_CLAIMABLE:
            return OpenTaskResult(
                OpenTaskStatus.SKIPPED_DONE_OR_CLAIMABLE,
                reason=result.reason,
            )
        if result.status != TaskSearchStatus.READY or result.go_match is None:
            raise NavigationError(
                f"Cannot find runnable task row on current screen for {spec.display_name}: {result.reason}"
            )

        self._annotate_daily_task_tap(spec, result)
        self.controller.tap(*result.go_match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)
        return OpenTaskResult(OpenTaskStatus.OPENED)

    def return_to_daily_tasks(self) -> bool:
        return self.go_to_daily_tasks()

    def return_to_daily_tasks_from_known_route(
        self,
        max_back_taps: int = 3,
        back_asset: Optional[Path] = None,
    ) -> bool:
        """Return from a known feature screen by using visible in-game back arrows only."""
        for _ in range(max_back_taps + 1):
            screen = self.controller.screenshot()
            detected = self.detector.detect(screen)
            if detected.scene == Scene.DAILY_TASKS:
                return True

            entry = self._match_daily_tasks_entry(screen)
            if entry is not None:
                self.controller.tap(*entry.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                continue

            if detected.scene == Scene.MAIN:
                return self.go_to_daily_tasks(max_steps=2)

            if self._tap_back_button_if_visible(screen, back_asset=back_asset):
                time.sleep(TRANSITION_WAIT_SECONDS)
                continue

            return False

        return self.go_to_daily_tasks(max_steps=2)

    def _daily_tasks_entry_assets(self) -> list[Path]:
        return sorted(SHARED_ASSETS_DIR.glob("daily_tasks_entry*.png"))

    def _match_daily_tasks_entry(self, screen):
        assets = self._daily_tasks_entry_assets()
        if not assets:
            return None
        return self.matcher.match_any(screen, assets, threshold=0.80, roi=self.DAILY_ENTRY_ROI)

    def _tap_back_button_if_visible(self, screen, back_asset: Optional[Path] = None) -> bool:
        back_button = back_asset or SHARED_ASSETS_DIR / "back_button.png"
        if not back_button.exists():
            return False
        match = self.matcher.match_template(screen, back_button, threshold=0.80)
        if match is None:
            return False
        self.controller.tap(*match.center)
        return True

    def _annotate_daily_task_tap(self, spec: TaskSpec, result: TaskSearchResult) -> None:
        label = result.label_match
        go = result.go_match
        if go is None:
            return

        boxes = []
        lines = [f"daily task: {spec.key} {spec.display_name}"]
        if label is not None:
            label_roi = DailyTaskFinder._task_list_roi(960, 540)
            status_roi = DailyTaskFinder._same_row_right_roi(960, 540, label)
            boxes.append((*label_roi, "label_roi"))
            boxes.append((*label.bbox, "label"))
            boxes.append((*status_roi, "status_roi"))
            lines.append(
                f"label {label.template_path.name} conf={label.confidence:.3f} "
                f"center={label.center}"
            )
        boxes.append((*go.bbox, "go"))
        lines.append(f"go {go.template_path.name} conf={go.confidence:.3f} center={go.center}")

        annotate = getattr(self.controller, "annotate_next_tap_debug", None)
        if annotate is not None:
            annotate(lines=lines, boxes=boxes)
        self.logger.log(" | ".join(lines), force=True)
