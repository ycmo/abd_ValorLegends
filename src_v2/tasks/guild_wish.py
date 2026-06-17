"""
guild_wish.py — 公會祈願（Phase 1 首個移植 task）

對照 src/tasks/guild_wish.py（182 行）：
  舊版：各 task 各自 copy _match_task_asset / _require_task_asset / _tap_task_asset
  新版：直接使用 BaseTask._wait_for / _require / _tap，業務邏輯乾淨呈現

行數：從 182 行 → ~80 行
"""
from __future__ import annotations

import time

from src.config import TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src_v2.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import Roi


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
        self._tap(
            "free wish button",
            "free_wish_button.png",
            roi=self.FREE_BUTTON_ROI,
            threshold=0.86,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        self._dismiss_reward_overlay_if_present()
        self._close_dialog()
        return "free guild wish completed"

    def execute_from_current_scene(self) -> str:
        if self._is_guild_wish_dialog_ready(timeout_seconds=0.8):
            return self.execute()
        # 已在 reward overlay 或 dialog 關閉中途
        self._dismiss_reward_overlay_if_present()
        self._close_dialog()
        return "free guild wish completed after reward overlay"

    # ------------------------------------------------------------------
    # 內部業務邏輯
    # ------------------------------------------------------------------

    def _require_guild_wish_dialog(self) -> None:
        self._require(
            "Guild Wish dialog title",
            "guild_wish_title.png",
            roi=self.TITLE_ROI,
            threshold=0.84,
            timeout_seconds=6.0,
        )
        self._require(
            "ordinary wish card",
            "ordinary_wish_label.png",
            roi=self.ORDINARY_LABEL_ROI,
            threshold=0.84,
            timeout_seconds=2.0,
        )

    def _is_guild_wish_dialog_ready(self, timeout_seconds: float = 1.0) -> bool:
        return (
            self._wait_for(
                "guild_wish_title.png",
                roi=self.TITLE_ROI,
                threshold=0.84,
                timeout_seconds=timeout_seconds,
            )
            is not None
            and self._wait_for(
                "ordinary_wish_label.png",
                roi=self.ORDINARY_LABEL_ROI,
                threshold=0.84,
                timeout_seconds=timeout_seconds,
            )
            is not None
            and self._wait_for(
                "free_wish_button.png",
                roi=self.FREE_BUTTON_ROI,
                threshold=0.86,
                timeout_seconds=timeout_seconds,
            )
            is not None
        )

    def _is_guild_wish_dialog_visible(self, timeout_seconds: float = 0.8) -> bool:
        return (
            self._wait_for(
                "guild_wish_title.png",
                roi=self.TITLE_ROI,
                threshold=0.84,
                timeout_seconds=timeout_seconds,
            )
            is not None
        )

    def _dismiss_reward_overlay_if_present(self) -> None:
        self._dismiss_overlay_by_blank_taps(
            is_closed=lambda: self._is_guild_wish_dialog_visible(timeout_seconds=0.8),
            max_taps=2,
            failure_message="Guild Wish reward overlay did not close after two blank-area taps",
        )

    def _close_dialog(self) -> None:
        self._require(
            "Guild Wish dialog title after free wish",
            "guild_wish_title.png",
            roi=self.TITLE_ROI,
            threshold=0.84,
            timeout_seconds=3.0,
        )
        self._tap(
            "close Guild Wish dialog",
            "close_button.png",
            roi=self.CLOSE_BUTTON_ROI,
            threshold=0.84,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        # 驗證 dialog 確實關閉
        deadline = time.time() + 3.0
        while time.time() <= deadline:
            if not self._is_guild_wish_dialog_visible(timeout_seconds=0.4):
                return
        raise TaskFailedError("Guild Wish dialog did not close after tapping X")
