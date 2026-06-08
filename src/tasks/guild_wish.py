from __future__ import annotations

import time
from typing import Optional

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult, Roi


class GuildWishTask(BaseTask):
    spec = TASK_SPECS["guild_wish"]
    required_assets = (
        "task_label.png",
        "guild_wish_title.png",
        "ordinary_wish_label.png",
        "free_wish_button.png",
        "close_button.png",
    )

    TITLE_ROI: Roi = (390, 45, 190, 80)
    ORDINARY_LABEL_ROI: Roi = (185, 120, 220, 80)
    FREE_BUTTON_ROI: Roi = (165, 360, 220, 95)
    CLOSE_BUTTON_ROI: Roi = (755, 45, 90, 80)
    task_scene_anchors = (
        TaskSceneAnchor("guild_wish_title.png", threshold=0.84, roi=TITLE_ROI),
        TaskSceneAnchor("close_button.png", threshold=0.84, roi=CLOSE_BUTTON_ROI),
    )

    def execute(self) -> str:
        self._require_guild_wish_dialog()
        self._tap_task_asset(
            "free guild wish",
            "free_wish_button.png",
            roi=self.FREE_BUTTON_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_reward_overlay_if_present()
        self._close_dialog()
        return "free guild wish completed"

    def execute_from_current_scene(self) -> str:
        if self._is_guild_wish_dialog_ready(timeout_seconds=0.8):
            return self.execute()

        self._dismiss_reward_overlay_if_present()
        self._close_dialog()
        return "free guild wish completed after reward overlay"

    def _require_guild_wish_dialog(self) -> None:
        self._require_task_asset(
            "Guild Wish dialog title",
            "guild_wish_title.png",
            roi=self.TITLE_ROI,
            threshold=0.84,
            timeout_seconds=6.0,
        )
        self._require_task_asset(
            "ordinary wish card",
            "ordinary_wish_label.png",
            roi=self.ORDINARY_LABEL_ROI,
            threshold=0.84,
            timeout_seconds=2.0,
        )

    def _is_guild_wish_dialog_ready(self, timeout_seconds: float = 1.0) -> bool:
        return (
            self._match_task_asset(
                "guild_wish_title.png",
                roi=self.TITLE_ROI,
                threshold=0.84,
                timeout_seconds=timeout_seconds,
            )
            is not None
            and self._match_task_asset(
                "ordinary_wish_label.png",
                roi=self.ORDINARY_LABEL_ROI,
                threshold=0.84,
                timeout_seconds=timeout_seconds,
            )
            is not None
            and self._match_task_asset(
                "free_wish_button.png",
                roi=self.FREE_BUTTON_ROI,
                threshold=0.86,
                timeout_seconds=timeout_seconds,
            )
            is not None
        )

    def _is_guild_wish_dialog_visible(self, timeout_seconds: float = 0.8) -> bool:
        return (
            self._match_task_asset(
                "guild_wish_title.png",
                roi=self.TITLE_ROI,
                threshold=0.84,
                timeout_seconds=timeout_seconds,
            )
            is not None
        )

    def _dismiss_reward_overlay_if_present(self) -> None:
        self.dismiss_reward_overlay_by_blank_taps(
            is_closed=lambda: self._is_guild_wish_dialog_visible(timeout_seconds=0.8),
            max_taps=2,
            failure_message="Guild Wish reward overlay did not close after two blank-area taps",
        )

    def _close_dialog(self) -> None:
        self._require_task_asset(
            "Guild Wish dialog title after free wish",
            "guild_wish_title.png",
            roi=self.TITLE_ROI,
            threshold=0.84,
            timeout_seconds=3.0,
        )
        self._tap_task_asset(
            "close Guild Wish dialog",
            "close_button.png",
            roi=self.CLOSE_BUTTON_ROI,
            threshold=0.84,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        deadline = time.time() + 3.0
        while time.time() <= deadline:
            if not self._match_task_asset(
                "guild_wish_title.png",
                roi=self.TITLE_ROI,
                threshold=0.84,
                timeout_seconds=0.4,
            ):
                return
        raise TaskFailedError("Guild Wish dialog did not close after tapping X")

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
            raise TaskFailedError(f"Guild Wish expected screen element not found: {label}")
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
