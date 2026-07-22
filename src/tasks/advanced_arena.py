from __future__ import annotations

import re
import time
from typing import Optional

import cv2
import numpy as np

from src.config import TASK_SPECS, TAP_COOLDOWN_SECONDS, TRANSITION_WAIT_SECONDS
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src.task_runner import BaseTask, TaskRunResult, TaskSceneAnchor, TaskState
from src.vision_matcher import MatchResult, Roi


class AdvancedArenaTask(BaseTask):
    spec = TASK_SPECS["advanced_arena"]
    required_assets = (
        "challenge_button.png",
        "free_button.png",
        "skip_formation_unchecked.png",
        "skip_formation_checked.png",
        "reward_item_card.png",
        "reward_exit_text.png",
        "continue_button.png",
        "challenge_dialog_close_button.png",
        "season_day_marker.png",
    )

    MAIN_CHALLENGE_ROI: Roi = (540, 470, 220, 60)
    SEASON_COUNTDOWN_ROI: Roi = (650, 135, 120, 35)
    POPUP_FREE_ROI: Roi = (560, 295, 165, 65)
    POPUP_CLOSE_ROI: Roi = (690, 75, 55, 55)
    POPUP_CLOSE_POINT = (716, 99)
    SKIP_FORMATION_ROI: Roi = (235, 395, 70, 50)
    REWARD_ITEM_ROI: Roi = (285, 205, 390, 90)
    REWARD_EXIT_TEXT_ROI: Roi = (300, 330, 365, 55)
    CONTINUE_ROI: Roi = (430, 485, 130, 45)
    BACK_POINT = (49, 42)

    TARGET_FREE_FIGHTS = 3
    RESULT_TIMEOUT_SECONDS = 180.0
    RESULT_MAX_ACTIONS = 24

    task_scene_anchors = (
        TaskSceneAnchor("challenge_button.png", threshold=0.86, roi=MAIN_CHALLENGE_ROI),
        TaskSceneAnchor("free_button.png", threshold=0.86, roi=POPUP_FREE_ROI),
        TaskSceneAnchor("challenge_dialog_close_button.png", threshold=0.86, roi=POPUP_CLOSE_ROI),
        TaskSceneAnchor("reward_item_card.png", threshold=0.86, roi=REWARD_ITEM_ROI),
        TaskSceneAnchor("continue_button.png", threshold=0.86, roi=CONTINUE_ROI),
    )

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None

    def run(self) -> TaskRunResult:
        return self._run_independent(require_current_scene=True)

    def run_from_current_scene(self) -> TaskRunResult:
        return self._run_independent(require_current_scene=True)

    def _run_independent(self, *, require_current_scene: bool) -> TaskRunResult:
        started = time.time()
        missing = self.missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(path) for path in missing),
                started,
            )

        try:
            if require_current_scene and not self.is_current_task_scene():
                raise TaskFailedError(f"Current screen is not the {self.spec.display_name} task scene")
            return self._result(TaskState.COMPLETED, self.execute(), started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except (BotError, TaskFailedError) as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def execute(self) -> str:
        fights = 0
        season_days = self._read_season_days_or_fail()
        if season_days == 0:
            self._tap_back_to_previous_page("advanced arena season has 0 days remaining")
            raise TaskFailedError("高階競技場賽季倒數剩 0 天，已返回；今天是最後一天，AFK 應停止")

        while fights < self.TARGET_FREE_FIGHTS:
            if not self._open_challenge_dialog():
                break
            if not self._ensure_skip_formation_selected():
                raise TaskFailedError("Advanced Arena could not enable skip formation")
            free_match = self._match_asset(
                "free_button.png",
                roi=self.POPUP_FREE_ROI,
                threshold=0.84,
                timeout_seconds=2.0,
            )
            if free_match is None:
                self._close_challenge_dialog()
                break

            self._tap_match(free_match, "advanced arena free challenge", wait_after_seconds=TRANSITION_WAIT_SECONDS)
            self._settle_battle_result()
            fights += 1

        return f"advanced arena free fights={fights}; season_days={season_days}"

    def _read_season_days_or_fail(self) -> int:
        screen = self.context.controller.screenshot()
        combined, confidence = self._read_green_countdown_digits(screen)
        marker_days, marker_text, marker_confidence = self._read_days_before_day_marker(screen)
        if marker_days is not None:
            days = marker_days
            method = "day_marker"
        else:
            days = parse_season_days(combined)
            method = "full_countdown_ocr"
        self.context.controller.save_annotated_debug(
            "advanced_arena_season_countdown",
            screen,
            lines=[
                "Advanced Arena season countdown OCR",
                f"roi={self.SEASON_COUNTDOWN_ROI}",
                f"text={combined or '<empty>'}",
                f"confidence={confidence:.3f}",
                f"day_marker_text={marker_text or '<empty>'}",
                f"day_marker_confidence={marker_confidence:.3f}",
                f"method={method}",
                f"days={days if days is not None else 'unknown'}",
            ],
            boxes=[(*self.SEASON_COUNTDOWN_ROI, "status_roi")],
            panel_position="right",
        )
        self._log(
            "Advanced Arena season countdown "
            f"text={combined or '<empty>'} confidence={confidence:.3f} "
            f"day_marker_text={marker_text or '<empty>'} "
            f"day_marker_confidence={marker_confidence:.3f} "
            f"method={method} "
            f"days={days if days is not None else 'unknown'}"
        )
        if days is None:
            raise TaskFailedError("Advanced Arena could not read season countdown days; stopped before fighting")
        return days

    def _read_green_countdown_digits(self, screen) -> tuple[str, float]:
        return self._read_green_digits(screen, self.SEASON_COUNTDOWN_ROI)

    def _read_days_before_day_marker(self, screen) -> tuple[Optional[int], str, float]:
        marker = self._match_asset_on_screen(
            screen,
            "season_day_marker.png",
            roi=self.SEASON_COUNTDOWN_ROI,
            threshold=0.82,
        )
        if marker is None:
            return None, "", 0.0
        countdown_x, countdown_y, _countdown_w, countdown_h = self.SEASON_COUNTDOWN_ROI
        marker_x, _marker_y, _marker_w, _marker_h = marker.bbox
        day_digits_width = max(0, marker_x - countdown_x)
        if day_digits_width <= 0:
            return None, "", marker.confidence
        text, confidence = self._read_green_digits(
            screen,
            (countdown_x, countdown_y, day_digits_width, countdown_h),
        )
        digits = re.findall(r"\d+", text)
        if not digits:
            return None, text, max(marker.confidence, confidence)
        return int("".join(digits)), text, min(marker.confidence, confidence)

    def _read_green_digits(self, screen, roi: Roi) -> tuple[str, float]:
        x, y, w, h = roi
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return "", 0.0
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (35, 80, 80), (95, 255, 255))
        prepared = np.full(crop.shape, 255, dtype=np.uint8)
        prepared[mask > 0] = (0, 0, 0)
        prepared = cv2.resize(prepared, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        reader = self._get_ocr_reader()
        try:
            results = reader.readtext(prepared, detail=1, allowlist="0123456789")
        except TypeError:
            results = reader.readtext(prepared, allowlist="0123456789")
        digits = []
        confidences = []
        for _box, text, confidence in results:
            clean = re.sub(r"\D+", "", str(text))
            if not clean:
                continue
            digits.append(clean)
            confidences.append(float(confidence))
        if not digits:
            return "", 0.0
        return " ".join(digits), min(confidences)

    def _open_challenge_dialog(self) -> bool:
        if self._match_asset(
            "free_button.png",
            roi=self.POPUP_FREE_ROI,
            threshold=0.84,
            timeout_seconds=0.6,
        ):
            return True

        challenge = self._match_asset(
            "challenge_button.png",
            roi=self.MAIN_CHALLENGE_ROI,
            threshold=0.86,
            timeout_seconds=3.0,
        )
        if challenge is None:
            return False
        self._tap_match(challenge, "advanced arena open challenge dialog", wait_after_seconds=TRANSITION_WAIT_SECONDS)
        if self._match_asset(
            "free_button.png",
            roi=self.POPUP_FREE_ROI,
            threshold=0.84,
            timeout_seconds=6.0,
        ) is not None:
            return True
        return self._match_asset(
            "challenge_dialog_close_button.png",
            roi=self.POPUP_CLOSE_ROI,
            threshold=0.84,
            timeout_seconds=1.0,
        ) is not None

    def _ensure_skip_formation_selected(self) -> bool:
        screen = self.context.controller.screenshot()
        checked = self._match_asset_on_screen(
            screen,
            "skip_formation_checked.png",
            roi=self.SKIP_FORMATION_ROI,
            threshold=0.86,
        )
        if checked is not None:
            return True

        unchecked = self._match_asset_on_screen(
            screen,
            "skip_formation_unchecked.png",
            roi=self.SKIP_FORMATION_ROI,
            threshold=0.86,
        )
        if unchecked is None:
            return False
        self._tap_match(unchecked, "advanced arena enable skip formation", wait_after_seconds=TAP_COOLDOWN_SECONDS)

        screen = self.context.controller.screenshot()
        return self._match_asset_on_screen(
            screen,
            "skip_formation_checked.png",
            roi=self.SKIP_FORMATION_ROI,
            threshold=0.86,
        ) is not None

    def _settle_battle_result(self) -> None:
        deadline = time.time() + self.RESULT_TIMEOUT_SECONDS
        actions = 0
        while time.time() <= deadline and actions < self.RESULT_MAX_ACTIONS:
            screen = self.context.controller.screenshot()
            if self._match_asset_on_screen(
                screen,
                "challenge_button.png",
                roi=self.MAIN_CHALLENGE_ROI,
                threshold=0.86,
            ):
                return

            reward = self._match_asset_on_screen(
                screen,
                "reward_item_card.png",
                roi=self.REWARD_ITEM_ROI,
                threshold=0.84,
            )
            if reward is not None:
                actions += 1
                self._tap_match(reward, "advanced arena choose reward item", wait_after_seconds=TRANSITION_WAIT_SECONDS)
                continue

            exit_text = self._match_asset_on_screen(
                screen,
                "reward_exit_text.png",
                roi=self.REWARD_EXIT_TEXT_ROI,
                threshold=0.84,
            )
            if exit_text is not None:
                actions += 1
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        "advanced arena exit reward lottery",
                        f"{exit_text.template_path.name} confidence={exit_text.confidence:.3f}",
                    ],
                    boxes=[(*exit_text.bbox, "status_roi")],
                )
                self.context.controller.tap(480, 360)
                time.sleep(TAP_COOLDOWN_SECONDS)
                continue

            continue_button = self._match_asset_on_screen(
                screen,
                "continue_button.png",
                roi=self.CONTINUE_ROI,
                threshold=0.84,
            )
            if continue_button is not None:
                actions += 1
                self._tap_match(
                    continue_button,
                    "advanced arena continue after result",
                    wait_after_seconds=TRANSITION_WAIT_SECONDS,
                )
                continue

            self._log("Advanced Arena waiting for battle result/actionable result screen")
            time.sleep(2.0)

        raise TaskFailedError("Advanced Arena timed out before returning to the main challenge screen")

    def _close_challenge_dialog(self) -> None:
        close = self._match_asset(
            "challenge_dialog_close_button.png",
            roi=self.POPUP_CLOSE_ROI,
            threshold=0.84,
            timeout_seconds=1.0,
        )
        if close is not None:
            self._tap_match(
                close,
                "advanced arena close challenge dialog; no free button found",
                wait_after_seconds=TRANSITION_WAIT_SECONDS,
            )
            return
        self.context.controller.annotate_next_tap_debug(
            lines=["advanced arena close challenge dialog by fixed X; no free button found"],
            boxes=[],
        )
        self.context.controller.tap(*self.POPUP_CLOSE_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _tap_back_to_previous_page(self, label: str) -> None:
        self.context.controller.annotate_next_tap_debug(lines=[label, "tap fixed top-left back"], boxes=[])
        self.context.controller.tap(*self.BACK_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            from src.ocr_utils import get_cached_easyocr_reader

            self._ocr_reader = get_cached_easyocr_reader(("en",), download_enabled=False)
        return self._ocr_reader

    def _match_asset(
        self,
        asset_name: str,
        *,
        roi: Roi,
        threshold: float,
        timeout_seconds: float,
    ) -> Optional[MatchResult]:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            match = self._match_asset_on_screen(screen, asset_name, roi=roi, threshold=threshold)
            if match is not None:
                return match
            time.sleep(0.35)
        return None

    def _match_asset_on_screen(
        self,
        screen,
        asset_name: str,
        *,
        roi: Roi,
        threshold: float,
    ) -> Optional[MatchResult]:
        return self.context.matcher.match_template(
            screen,
            self.asset_path(asset_name),
            threshold=threshold,
            roi=roi,
        )

    def _tap_match(
        self,
        match: MatchResult,
        label: str,
        *,
        wait_after_seconds: float,
    ) -> None:
        self.context.controller.annotate_next_tap_debug(
            lines=[
                label,
                f"{match.template_path.name} confidence={match.confidence:.3f}",
            ],
            boxes=[(*match.bbox, "go")],
        )
        self.context.controller.tap(*match.center)
        time.sleep(wait_after_seconds)


def parse_season_days(text: str) -> Optional[int]:
    raw = str(text)
    normalized = raw.replace(" ", "")
    match = re.search(r"(\d+)\s*天", normalized)
    if match:
        return int(match.group(1))
    if "天" not in normalized:
        if any(marker in normalized for marker in ("小", "時", "时")):
            return 0
        digit_groups = re.findall(r"\d+", raw)
        if len(digit_groups) >= 2:
            return int(digit_groups[0])
        if len(digit_groups) == 1:
            digits_only = digit_groups[0]
            if len(digits_only) <= 2 and int(digits_only) <= 24:
                return 0
            if len(digits_only) >= 5:
                two_digit_days = int(digits_only[:2])
                if 1 <= two_digit_days <= 60:
                    return two_digit_days
                one_digit_days = int(digits_only[:1])
                if 1 <= one_digit_days <= 9:
                    return one_digit_days
            if len(digits_only) == 3:
                hours = int(digits_only[-2:])
                if hours <= 23:
                    return int(digits_only[:1])
            if len(digits_only) == 4:
                hours = int(digits_only[-2:])
                if hours <= 23:
                    return int(digits_only[:2])
            return None
        return None
    digits = re.findall(r"\d+", normalized)
    if not digits:
        return None
    return int(digits[0])
