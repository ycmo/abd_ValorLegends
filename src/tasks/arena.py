from __future__ import annotations

import time
from typing import Optional

import cv2
import numpy as np

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.ocr_utils import extract_arena_powers_easyocr
from src.scene_detector import Scene
from src.task_runner import BaseTask
from src.vision_matcher import MatchResult, Roi


class ArenaTask(BaseTask):
    spec = TASK_SPECS["arena"]
    required_assets = (
        "task_label.png",
        "arena_main_anchor.png",
        "opponent_list_anchor.png",
        "multi_challenge_button.png",
        "challenge_button.png",
        "continue_button.png",
        "arena_back_button.png",
    )

    MAX_POWER_K = 7000
    TARGET_FIGHTS = 8
    MAX_ROUNDS = 5
    OCR_MIN_CONFIDENCE = 0.70

    ARENA_MAIN_ROI: Roi = (760, 0, 200, 105)
    OPPONENT_LIST_ROI: Roi = (760, 0, 160, 120)
    MULTI_CHALLENGE_ROI: Roi = (430, 455, 230, 80)
    ACTION_BUTTON_ROI: Roi = (680, 420, 220, 85)
    CONTINUE_BUTTON_ROI: Roi = (380, 470, 210, 70)
    BACK_BUTTON_ROI: Roi = (0, 0, 100, 90)

    CHECKBOX_X = (436, 812)
    CHECKBOX_Y = (147, 223, 299, 375)
    CHECKED_GREEN_RATIO = 0.08
    UNCHECKED_GREEN_RATIO = 0.02

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None

    def execute(self) -> str:
        total_fought = 0
        rounds = 0
        while total_fought < self.TARGET_FIGHTS:
            rounds += 1
            if rounds > self.MAX_ROUNDS:
                raise TaskFailedError(
                    f"Arena exceeded {self.MAX_ROUNDS} rounds before reaching {self.TARGET_FIGHTS} fights"
                )

            self._open_opponent_list()
            round_fights = self._uncheck_overpowered_and_start()
            total_fought += round_fights
            self._wait_for_battle_result_and_continue()
            self._wait_for_arena_main("after battle result")

        self._return_to_daily_tasks()
        return f"Arena fights: {total_fought} across {rounds} round(s)"

    def _open_opponent_list(self) -> None:
        if self._match_task_asset(
            "opponent_list_anchor.png",
            roi=self.OPPONENT_LIST_ROI,
            threshold=0.84,
            timeout_seconds=0.8,
        ):
            return

        self._require_arena_main()
        self._tap_task_asset(
            "multi challenge",
            "multi_challenge_button.png",
            roi=self.MULTI_CHALLENGE_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._require_task_asset(
            "Arena opponent list",
            "opponent_list_anchor.png",
            roi=self.OPPONENT_LIST_ROI,
            threshold=0.84,
            timeout_seconds=6.0,
        )

    def _uncheck_overpowered_and_start(self) -> int:
        screen = self._require_opponent_list_screen()
        opponents = self._read_opponents(screen)

        for opponent in opponents:
            if opponent["power_k"] <= self.MAX_POWER_K:
                continue
            state = self._checkbox_state(screen, opponent["row"], opponent["col"])
            if state == "checked":
                self.context.controller.tap(*self._checkbox_center(opponent["row"], opponent["col"]))
                time.sleep(TAP_COOLDOWN_SECONDS)
                screen = self._require_opponent_list_screen()
                if self._checkbox_state(screen, opponent["row"], opponent["col"]) != "unchecked":
                    raise TaskFailedError(
                        "Arena failed to verify over-7000k opponent was unchecked: "
                        f"row={opponent['row']} col={opponent['col']} power={opponent['power_text']}"
                    )
            elif state != "unchecked":
                raise TaskFailedError(
                    "Arena checkbox state is uncertain for over-7000k opponent: "
                    f"row={opponent['row']} col={opponent['col']} power={opponent['power_text']}"
                )

        screen = self._require_opponent_list_screen()
        selected_count = self._count_checked_opponents(screen)
        if selected_count <= 0:
            raise TaskFailedError("Arena has no checked safe opponents after filtering over-7000k targets")

        self._tap_task_asset(
            "start Arena challenge",
            "challenge_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        return selected_count

    def _read_opponents(self, screen) -> list[dict]:
        opponents = extract_arena_powers_easyocr(screen, reader=self._get_ocr_reader())
        uncertain = [
            item
            for item in opponents
            if item["power_k"] < 0 or item.get("confidence", 0.0) < self.OCR_MIN_CONFIDENCE
        ]
        if uncertain:
            detail = "; ".join(
                f"row={item['row']} col={item['col']} text={item['power_text']!r} "
                f"conf={item.get('confidence', 0.0):.3f}"
                for item in uncertain
            )
            raise TaskFailedError(f"Arena OCR is uncertain; stopping before selecting opponents: {detail}")
        return opponents

    def _wait_for_battle_result_and_continue(self) -> None:
        deadline = time.time() + 150.0
        while time.time() <= deadline:
            match = self._match_task_asset(
                "continue_button.png",
                roi=self.CONTINUE_BUTTON_ROI,
                threshold=0.82,
                timeout_seconds=0.6,
            )
            if match is not None:
                self.context.controller.tap(*match.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                return
            time.sleep(2.0)
        raise TaskFailedError("Arena timed out waiting for battle continue button")

    def _wait_for_arena_main(self, label: str) -> None:
        deadline = time.time() + 8.0
        while time.time() <= deadline:
            if self._match_task_asset(
                "arena_main_anchor.png",
                roi=self.ARENA_MAIN_ROI,
                threshold=0.84,
                timeout_seconds=0.6,
            ):
                return
        raise TaskFailedError(f"Arena main screen not visible {label}")

    def _return_to_daily_tasks(self) -> None:
        if self._match_task_asset(
            "arena_main_anchor.png",
            roi=self.ARENA_MAIN_ROI,
            threshold=0.84,
            timeout_seconds=1.0,
        ):
            self._tap_task_asset(
                "leave Arena page",
                "arena_back_button.png",
                roi=self.BACK_BUTTON_ROI,
                threshold=0.86,
                wait_after_seconds=TRANSITION_WAIT_SECONDS,
            )

        if self._is_daily_tasks_visible():
            return
        if self.context.navigator.go_to_daily_tasks(max_steps=3):
            return
        raise TaskFailedError("Arena completed, but could not return to Daily Tasks safely")

    def _require_arena_main(self) -> MatchResult:
        return self._require_task_asset(
            "Arena main screen",
            "arena_main_anchor.png",
            roi=self.ARENA_MAIN_ROI,
            threshold=0.84,
            timeout_seconds=8.0,
        )

    def _require_opponent_list_screen(self):
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("opponent_list_anchor.png"),
            threshold=0.84,
            roi=self.OPPONENT_LIST_ROI,
        )
        if match is None:
            raise TaskFailedError("Arena opponent list is not visible")
        return screen

    def _count_checked_opponents(self, screen) -> int:
        count = 0
        for row in range(1, 5):
            for col in range(1, 3):
                state = self._checkbox_state(screen, row, col)
                if state == "checked":
                    count += 1
                elif state == "unknown":
                    raise TaskFailedError(f"Arena checkbox state is uncertain: row={row} col={col}")
        return count

    def _checkbox_state(self, screen, row: int, col: int) -> str:
        x, y = self._checkbox_center(row, col)
        roi = screen[max(0, y - 15) : y + 15, max(0, x - 15) : x + 15]
        if roi.size == 0:
            return "unknown"
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (40, 80, 100), (90, 255, 255))
        ratio = float(np.sum(mask > 0) / mask.size)
        if ratio >= self.CHECKED_GREEN_RATIO:
            return "checked"
        if ratio <= self.UNCHECKED_GREEN_RATIO:
            return "unchecked"
        return "unknown"

    def _checkbox_center(self, row: int, col: int) -> tuple[int, int]:
        return self.CHECKBOX_X[col - 1], self.CHECKBOX_Y[row - 1]

    def _is_daily_tasks_visible(self) -> bool:
        screen = self.context.controller.screenshot()
        return self.context.detector.detect(screen).scene == Scene.DAILY_TASKS

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            from src.ocr_utils import build_easyocr_reader

            self._ocr_reader = build_easyocr_reader()
        return self._ocr_reader

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
            raise TaskFailedError(f"Arena expected screen element not found: {label}")
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
