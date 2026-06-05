from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from src.adb_controller import DeviceController
from src.config import SHARED_ASSETS_DIR, TRANSITION_WAIT_SECONDS, TaskSpec
from src.daily_task_finder import DailyTaskFinder, TaskSearchStatus
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

    def __init__(
        self,
        controller: DeviceController,
        matcher: VisionMatcher,
        detector: SceneDetector,
        finder: DailyTaskFinder,
    ):
        self.controller = controller
        self.matcher = matcher
        self.detector = detector
        self.finder = finder

    def go_to_daily_tasks(self, max_steps: int = 6) -> bool:
        daily_entry = SHARED_ASSETS_DIR / "daily_tasks_entry.png"
        for _ in range(max_steps):
            screen = self.controller.screenshot()
            detected = self.detector.detect(screen)
            if detected.scene == Scene.DAILY_TASKS:
                return True

            entry = None
            if daily_entry.exists():
                entry = self.matcher.match_template(screen, daily_entry, threshold=0.80)
            if entry is not None:
                self.controller.tap(*entry.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                continue

            if detected.scene == Scene.MAIN:
                if not daily_entry.exists():
                    raise MissingAssetError(
                        f"Main screen detected but daily task entry template is missing: {daily_entry}"
                    )
                entry = self.matcher.match_template(screen, daily_entry, threshold=0.80)
                if entry is None:
                    raise NavigationError("Main screen detected but daily task entry was not found")
                self.controller.tap(*entry.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                continue

            return False
        return False

    def open_task_from_daily(self, spec: TaskSpec) -> OpenTaskResult:
        if not self.go_to_daily_tasks():
            raise NavigationError("Cannot reach daily tasks before opening task")

        result = self.finder.scroll_to_task(spec)
        if result.status == TaskSearchStatus.DONE_OR_CLAIMABLE:
            return OpenTaskResult(
                OpenTaskStatus.SKIPPED_DONE_OR_CLAIMABLE,
                reason=result.reason,
            )
        if result.status != TaskSearchStatus.READY or result.go_match is None:
            raise NavigationError(f"Cannot find runnable task row for {spec.display_name}: {result.reason}")

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
        daily_entry = SHARED_ASSETS_DIR / "daily_tasks_entry.png"
        for _ in range(max_back_taps + 1):
            screen = self.controller.screenshot()
            detected = self.detector.detect(screen)
            if detected.scene == Scene.DAILY_TASKS:
                return True

            if daily_entry.exists():
                entry = self.matcher.match_template(screen, daily_entry, threshold=0.80)
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

    def _tap_back_button_if_visible(self, screen, back_asset: Optional[Path] = None) -> bool:
        back_button = back_asset or SHARED_ASSETS_DIR / "back_button.png"
        if not back_button.exists():
            return False
        match = self.matcher.match_template(screen, back_button, threshold=0.80)
        if match is None:
            return False
        self.controller.tap(*match.center)
        return True
