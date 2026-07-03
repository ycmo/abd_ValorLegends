from __future__ import annotations

import time
from typing import Optional

from src.account_state import read_current_account
from src.config import SHARED_ASSETS_DIR, TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.scene_detector import Scene
from src.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult, Roi


class EquipmentEnhanceTask(BaseTask):
    spec = TASK_SPECS["equipment_enhance"]
    required_assets = (
        "hero_tab.png",
        "hero_primary.png",
        "hero_fallback.png",
        "hero_fallback_face.png",
        "evil_filter.png",
        "hero_info_back_button.png",
        "idle_tab.png",
        "equipment_tab.png",
        "upgrade_sword.png",
        "enhance_button_text.png",
        "auto_add_button.png",
    )

    HERO_GRID_ROI: Roi = (0, 40, 960, 380)
    HERO_FALLBACK_ROI: Roi = (0, 40, 330, 330)
    HERO_TAB_ROI: Roi = (650, 490, 120, 50)
    HERO_FILTER_ROI: Roi = (300, 400, 360, 90)
    EQUIPMENT_TAB_ROI: Roi = (0, 120, 100, 110)
    EQUIPMENT_LIST_ROI: Roi = (610, 70, 350, 150)
    EQUIPMENT_POPUP_ENHANCE_ROI: Roi = (410, 420, 150, 60)
    AUTO_ADD_ROI: Roi = (530, 400, 220, 90)
    ENHANCE_CONFIRM_ROI: Roi = (210, 410, 190, 70)
    ENHANCE_CLOSE_POINT = (796, 79)
    HERO_INFO_BACK_ROI: Roi = (0, 0, 110, 70)
    IDLE_TAB_POINT = (468, 514)
    DAILY_ENTRY_ROI: Roi = (870, 0, 90, 120)
    DAILY_ENTRY_POINT = (920, 49)
    PRIMARY_HERO_ACCOUNTS = {"em3", "tiger"}
    task_scene_anchors = (
        TaskSceneAnchor("hero_tab.png", threshold=0.78, roi=HERO_TAB_ROI),
        TaskSceneAnchor("equipment_tab.png", threshold=0.78, roi=EQUIPMENT_TAB_ROI),
        TaskSceneAnchor("auto_add_button.png", threshold=0.82, roi=AUTO_ADD_ROI),
    )

    def execute(self) -> str:
        self.execute_from_current_scene()
        return "enhanced equipment once"

    def execute_from_current_scene(self) -> str:
        self._select_target_hero()
        self._open_equipment_tab()
        self._open_upgrade_equipment()
        self._open_enhance_dialog()
        self._auto_add_materials()
        self._tap_enhance_once()
        self._close_enhance_dialog()
        self._return_to_daily_tasks()
        return "enhanced equipment once"

    def _select_target_hero(self) -> None:
        account = read_current_account(default="default")
        self._ensure_hero_list_filter()
        hero = None
        if account in self.PRIMARY_HERO_ACCOUNTS:
            hero = self._match_task_asset(
                "hero_primary.png",
                roi=self.HERO_GRID_ROI,
                threshold=0.82,
                timeout_seconds=1.0,
            )
        if hero is None:
            hero = self._match_top_left_fallback_hero()
        if hero is None:
            self._open_hero_list()
            if account in self.PRIMARY_HERO_ACCOUNTS:
                hero = self._match_task_asset(
                    "hero_primary.png",
                    roi=self.HERO_GRID_ROI,
                    threshold=0.82,
                    timeout_seconds=1.0,
                )
            if hero is None:
                hero = self._match_top_left_fallback_hero()
        if hero is None:
            self._save_target_hero_debug(account)
            raise TaskFailedError(f"Equipment Enhance target hero not found for account={account}")
        self.context.controller.tap(*hero.center)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _ensure_hero_list_filter(self) -> None:
        if self._match_task_asset(
            "evil_filter.png",
            roi=self.HERO_FILTER_ROI,
            threshold=0.78,
            timeout_seconds=0.8,
        ) is None:
            self._open_hero_list()
        self._tap_task_asset(
            "select evil hero filter",
            "evil_filter.png",
            roi=self.HERO_FILTER_ROI,
            threshold=0.78,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _open_hero_list(self) -> None:
        self._tap_task_asset(
            "open hero list",
            "hero_tab.png",
            roi=self.HERO_TAB_ROI,
            threshold=0.78,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _match_top_left_fallback_hero(self) -> Optional[MatchResult]:
        screen = self.context.controller.screenshot()
        for asset_name, threshold in (("hero_fallback.png", 0.82), ("hero_fallback_face.png", 0.76)):
            match = self._match_top_left_fallback_asset(screen, asset_name, threshold=threshold)
            if match is not None:
                return match
        return None

    def _match_top_left_fallback_asset(self, screen, asset_name: str, *, threshold: float) -> Optional[MatchResult]:
        path = self.asset_path(asset_name)
        match_all = getattr(self.context.matcher, "match_template_all", None)
        if match_all is not None:
            matches = match_all(
                screen,
                path,
                threshold=threshold,
                roi=self.HERO_FALLBACK_ROI,
                max_results=12,
                min_center_distance=24,
            )
            if matches:
                return sorted(matches, key=lambda item: (item.center[1], item.center[0]))[0]
        return self.context.matcher.match_template(
            screen,
            path,
            threshold=threshold,
            roi=self.HERO_FALLBACK_ROI,
        )

    def _save_target_hero_debug(self, account: str) -> None:
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is None:
            return
        screen = self.context.controller.screenshot()
        boxes = [(*self.HERO_FALLBACK_ROI, "hero_fallback_roi")]
        lines = [f"equipment enhance target hero not found account={account}"]
        best_match = getattr(self.context.matcher, "best_template_match", None)
        if best_match is not None:
            for asset_name in ("hero_primary.png", "hero_fallback.png", "hero_fallback_face.png"):
                probe = best_match(screen, self.asset_path(asset_name), roi=self.HERO_GRID_ROI)
                if probe is None:
                    lines.append(f"{asset_name}: no probe")
                    continue
                boxes.append((*probe.bbox, "label"))
                lines.append(f"{asset_name}: best={probe.confidence:.3f} center={probe.center}")
        save_debug(
            "equipment_enhance_target_hero_not_found",
            screen,
            lines=lines,
            boxes=boxes,
        )

    def _open_equipment_tab(self) -> None:
        if self._match_task_asset(
            "upgrade_sword.png",
            roi=self.EQUIPMENT_LIST_ROI,
            threshold=0.82,
            timeout_seconds=1.0,
        ):
            return
        self._tap_task_asset(
            "open hero equipment tab",
            "equipment_tab.png",
            roi=self.EQUIPMENT_TAB_ROI,
            threshold=0.82,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _open_upgrade_equipment(self) -> None:
        self._tap_task_asset(
            "open upgrade equipment",
            "upgrade_sword.png",
            roi=self.EQUIPMENT_LIST_ROI,
            threshold=0.82,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _open_enhance_dialog(self) -> None:
        self._tap_task_asset(
            "open enhance dialog",
            "enhance_button_text.png",
            roi=self.EQUIPMENT_POPUP_ENHANCE_ROI,
            threshold=0.82,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _auto_add_materials(self) -> None:
        self._tap_task_asset(
            "auto add enhance materials",
            "auto_add_button.png",
            roi=self.AUTO_ADD_ROI,
            threshold=0.82,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _tap_enhance_once(self) -> None:
        self._tap_task_asset(
            "enhance equipment once",
            "enhance_button_text.png",
            roi=self.ENHANCE_CONFIRM_ROI,
            threshold=0.75,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )

    def _close_enhance_dialog(self) -> None:
        if hasattr(self.context.controller, "annotate_next_tap_debug"):
            self.context.controller.annotate_next_tap_debug(
                lines=["equipment enhance close dialog"],
            )
        self.context.controller.tap(*self.ENHANCE_CLOSE_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _return_to_daily_tasks(self) -> None:
        if self._is_daily_tasks_visible():
            return
        if self._match_task_asset(
            "auto_add_button.png",
            roi=self.AUTO_ADD_ROI,
            threshold=0.82,
            timeout_seconds=0.6,
        ):
            self._close_enhance_dialog()
        if self._match_task_asset(
            "hero_info_back_button.png",
            roi=self.HERO_INFO_BACK_ROI,
            threshold=0.86,
            timeout_seconds=0.8,
        ):
            self._tap_task_asset(
                "back from hero equipment",
                "hero_info_back_button.png",
                roi=self.HERO_INFO_BACK_ROI,
                threshold=0.86,
                wait_after_seconds=TRANSITION_WAIT_SECONDS,
            )
        elif self._match_shared_asset(
            "back_button2.png",
            roi=self.HERO_INFO_BACK_ROI,
            threshold=0.86,
            timeout_seconds=0.5,
        ):
            self._tap_shared_asset(
                "back from hero equipment",
                "back_button2.png",
                roi=self.HERO_INFO_BACK_ROI,
                threshold=0.86,
                wait_after_seconds=TRANSITION_WAIT_SECONDS,
            )
        self._tap_idle_tab()
        if self._is_daily_tasks_visible():
            return
        self._tap_daily_entry_from_idle()
        if self._is_daily_tasks_visible():
            return
        if self.context.navigator.go_to_daily_tasks(max_steps=4):
            return
        raise TaskFailedError("Equipment Enhance completed, but could not return to Daily Tasks safely")

    def _is_daily_tasks_visible(self) -> bool:
        screen = self.context.controller.screenshot()
        return self.context.detector.detect(screen).scene == Scene.DAILY_TASKS

    def _tap_idle_tab(self) -> None:
        match = self._match_task_asset(
            "idle_tab.png",
            roi=(380, 480, 190, 60),
            threshold=0.86,
            timeout_seconds=0.8,
        )
        if match is not None:
            annotate = getattr(self.context.controller, "annotate_next_tap_debug", None)
            if annotate is not None:
                annotate(
                    lines=[f"equipment enhance return: tap idle tab conf={match.confidence:.3f}"],
                    boxes=[(*match.bbox, "idle_tab")],
                )
            self.context.controller.tap(*match.center)
            time.sleep(TRANSITION_WAIT_SECONDS)
            return

        annotate = getattr(self.context.controller, "annotate_next_tap_debug", None)
        if annotate is not None:
            annotate(lines=["equipment enhance return: tap idle tab"])
        self.context.controller.tap(*self.IDLE_TAB_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _tap_daily_entry_from_idle(self) -> None:
        for asset_name in ("daily_tasks_entry_alt.png", "daily_tasks_entry.png"):
            match = self._match_shared_asset(
                asset_name,
                roi=self.DAILY_ENTRY_ROI,
                threshold=0.68,
                timeout_seconds=0.8,
            )
            if match is not None:
                annotate = getattr(self.context.controller, "annotate_next_tap_debug", None)
                if annotate is not None:
                    annotate(
                        lines=[
                            f"equipment enhance return: tap daily task entry {asset_name} "
                            f"conf={match.confidence:.3f}"
                        ],
                        boxes=[(*match.bbox, "daily_entry")],
                    )
                self.context.controller.tap(*match.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                return

        annotate = getattr(self.context.controller, "annotate_next_tap_debug", None)
        if annotate is not None:
            annotate(lines=["equipment enhance return: fallback tap daily task entry"])
        self.context.controller.tap(*self.DAILY_ENTRY_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

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

    def _tap_shared_asset(
        self,
        label: str,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        wait_after_seconds: float = TAP_COOLDOWN_SECONDS,
    ) -> MatchResult:
        match = self._require_shared_asset(label, asset_name, roi=roi, threshold=threshold)
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
            raise TaskFailedError(f"Equipment Enhance expected screen element not found: {label}")
        return match

    def _require_shared_asset(
        self,
        label: str,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
    ) -> MatchResult:
        match = self._match_shared_asset(asset_name, roi=roi, threshold=threshold, timeout_seconds=timeout_seconds)
        if match is None:
            raise TaskFailedError(f"Equipment Enhance expected shared screen element not found: {label}")
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

    def _match_shared_asset(
        self,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
    ) -> Optional[MatchResult]:
        path = SHARED_ASSETS_DIR / asset_name
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(screen, path, threshold=threshold, roi=roi)
            if match is not None:
                return match
            time.sleep(0.35)
        return None
