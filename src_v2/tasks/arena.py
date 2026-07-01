"""
arena.py — Arena (Phase 3)
"""
from __future__ import annotations

import time
from typing import Optional

import cv2
import numpy as np

from src.config import TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.ocr_utils import extract_arena_powers_easyocr, get_cached_easyocr_reader
from src_v2.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import Roi


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

    MAX_POWER_K = 6500
    TARGET_FIGHTS = 8
    MAX_ROUNDS = 5
    OCR_MIN_CONFIDENCE = 0.60
    OCR_LOW_POWER_SAFE_MAX_K = 1000
    OCR_LOW_POWER_MIN_CONFIDENCE = 0.50
    OCR_OVERPOWERED_MIN_CONFIDENCE = 0.50

    ARENA_MAIN_ROI: Roi = (760, 0, 200, 105)
    OPPONENT_LIST_ROI: Roi = (760, 0, 160, 120)
    MULTI_CHALLENGE_ROI: Roi = (430, 455, 230, 80)
    ACTION_BUTTON_ROI: Roi = (680, 420, 220, 85)
    CONTINUE_BUTTON_ROI: Roi = (380, 470, 210, 70)
    BACK_BUTTON_ROI: Roi = (0, 0, 100, 90)

    task_scene_anchors = (
        TaskSceneAnchor("arena_main_anchor.png", threshold=0.84, roi=ARENA_MAIN_ROI),
        TaskSceneAnchor("opponent_list_anchor.png", threshold=0.84, roi=OPPONENT_LIST_ROI),
    )

    CHECKBOX_X = (436, 812)
    CHECKBOX_Y = (147, 223, 299, 375)
    CHECKED_GREEN_RATIO = 0.08
    UNCHECKED_GREEN_RATIO = 0.02

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None

    def execute(self) -> str:
        self._require("Arena main screen", "arena_main_anchor.png", roi=self.ARENA_MAIN_ROI, threshold=0.84, timeout_seconds=8.0)

        total_fought = 0
        rounds = 0

        while total_fought < self.TARGET_FIGHTS:
            rounds += 1
            if rounds > self.MAX_ROUNDS:
                raise TaskFailedError(
                    f"Arena exceeded {self.MAX_ROUNDS} rounds before reaching {self.TARGET_FIGHTS} fights"
                )

            self._open_opponent_list()
            
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(
                screen, self._asset_path("opponent_list_anchor.png"), threshold=0.84, roi=self.OPPONENT_LIST_ROI
            )
            if match is None:
                raise TaskFailedError("Arena opponent list is not visible")
            
            round_fights = self._uncheck_overpowered_and_start(screen)
            total_fought += round_fights
            
            self._wait_for_battle_result_and_continue()
            self._wait_for_arena_main()

        return f"Arena fights: {total_fought} across {rounds} round(s)"

    def _open_opponent_list(self) -> None:
        if self._wait_for(
            "opponent_list_anchor.png",
            roi=self.OPPONENT_LIST_ROI,
            threshold=0.84,
            timeout_seconds=0.8,
        ) is not None:
            return

        self._require("Arena main screen", "arena_main_anchor.png", roi=self.ARENA_MAIN_ROI, threshold=0.84, timeout_seconds=8.0)
        
        self._tap(
            "multi challenge",
            "multi_challenge_button.png",
            roi=self.MULTI_CHALLENGE_ROI,
            threshold=0.86,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        
        self._require(
            "Arena opponent list",
            "opponent_list_anchor.png",
            roi=self.OPPONENT_LIST_ROI,
            threshold=0.84,
            timeout_seconds=6.0,
        )

    def _uncheck_overpowered_and_start(self, screen) -> int:
        opponents = self._read_opponents(screen)

        for opponent in opponents:
            if opponent["power_k"] <= self.MAX_POWER_K:
                continue
            
            state = self._checkbox_state(screen, opponent["row"], opponent["col"])
            if state == "checked":
                center = self._checkbox_center(opponent["row"], opponent["col"])
                self.context.controller.tap(*center)
                time.sleep(TAP_COOLDOWN_SECONDS)
                
                screen = self.context.controller.screenshot()
                if self._checkbox_state(screen, opponent["row"], opponent["col"]) != "unchecked":
                    raise TaskFailedError("Arena failed to verify over-6500k opponent was unchecked")
            elif state != "unchecked":
                raise TaskFailedError("Arena checkbox state is uncertain for over-6500k opponent")

        screen = self.context.controller.screenshot()
        selected_count = self._count_checked_opponents(screen)
        
        if selected_count <= 0:
            raise TaskFailedError("No safe opponents or OCR failed")

        self._tap(
            "start Arena challenge",
            "challenge_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=0.86,
            wait_after=TRANSITION_WAIT_SECONDS,
        )
        return selected_count

    def _read_opponents(self, screen) -> list[dict]:
        opponents = extract_arena_powers_easyocr(screen, reader=self._get_ocr_reader())
        uncertain = [item for item in opponents if not self._is_ocr_power_confident_enough(item)]
        if uncertain:
            raise TaskFailedError("Arena OCR is uncertain")
        return opponents

    def _is_ocr_power_confident_enough(self, item: dict) -> bool:
        power_k = item["power_k"]
        confidence = item.get("confidence", 0.0)
        if power_k < 0:
            return False
        if confidence >= self.OCR_MIN_CONFIDENCE:
            return True
        if power_k > self.MAX_POWER_K and confidence >= self.OCR_OVERPOWERED_MIN_CONFIDENCE:
            return True
        if power_k <= self.OCR_LOW_POWER_SAFE_MAX_K and confidence >= self.OCR_LOW_POWER_MIN_CONFIDENCE:
            return True
        return False

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

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            self._ocr_reader = get_cached_easyocr_reader(("en",), download_enabled=False)
        return self._ocr_reader

    def _wait_for_battle_result_and_continue(self) -> None:
        match = self._wait_for("continue_button.png", roi=self.CONTINUE_BUTTON_ROI, threshold=0.82, timeout_seconds=150.0)
        if match is not None:
            self.context.controller.tap(*match.center)
            time.sleep(TRANSITION_WAIT_SECONDS)
        else:
            raise TaskFailedError("Battle result continue button not found after 150s")

    def _wait_for_arena_main(self) -> None:
        if self._wait_for("arena_main_anchor.png", roi=self.ARENA_MAIN_ROI, threshold=0.84, timeout_seconds=8.0) is None:
            raise TaskFailedError("Did not return to arena main screen after battle")

    def _pre_return_hook(self) -> None:
        if self._wait_for("opponent_list_anchor.png", roi=self.OPPONENT_LIST_ROI, threshold=0.84, timeout_seconds=1.0) is not None:
            self.context.controller.tap(846, 70)
            time.sleep(TRANSITION_WAIT_SECONDS)
            
        if self._wait_for("arena_main_anchor.png", roi=self.ARENA_MAIN_ROI, threshold=0.84, timeout_seconds=3.0) is not None:
            self._tap("arena back", "arena_back_button.png", roi=self.BACK_BUTTON_ROI, threshold=0.86, wait_after=TRANSITION_WAIT_SECONDS)
