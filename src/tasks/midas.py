from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

import cv2

from src.config import SHARED_ASSETS_DIR, TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import BotError, TaskFailedError
from src.task_runner import BaseTask, TaskSceneAnchor, TaskRunResult, TaskState
from src.vision_matcher import MatchResult, Roi


@dataclass(frozen=True)
class MidasAutoResult:
    clicked: bool
    cooldown_seconds: Optional[int] = None
    ocr_text: str = ""
    ocr_confidence: float = 0.0

    @property
    def cooldown_valid(self) -> bool:
        return self.cooldown_seconds is not None


class MidasTask(BaseTask):
    spec = TASK_SPECS["midas"]
    required_assets = (
        "task_label.png",
        "midas_title.png",
        "free_button.png",
        "gem_20_button.png",
        "gem_50_button.png",
        "midas_close_button.png",
        "reward_title.png",
    )

    TITLE_ROI: Roi = (360, 45, 250, 70)
    FREE_BUTTON_ROI: Roi = (160, 410, 190, 75)
    GEM_20_BUTTON_ROI: Roi = (370, 410, 190, 75)
    GEM_50_BUTTON_ROI: Roi = (580, 410, 190, 75)
    CLOSE_BUTTON_ROI: Roi = (735, 45, 80, 70)
    REWARD_TITLE_ROI: Roi = (330, 100, 300, 100)
    BUSY_OVERLAY_ROI: Roi = (400, 180, 180, 180)
    BUSY_OVERLAY_THRESHOLD = 0.86
    BUSY_WAIT_MAX_SECONDS = 90.0
    ACTIVE_BUTTON_THRESHOLD = 0.92
    REWARD_WAIT_SECONDS = 12.0
    STATE_POLL_SECONDS = 1.0
    MAX_ALLOWED_TAPS = 12
    COOLDOWN_OCR_ROI: Roi = (470, 116, 100, 38)
    COOLDOWN_OCR_MIN_CONFIDENCE = 0.50
    COOLDOWN_MAX_SECONDS = 8 * 60 * 60
    task_scene_anchors = (
        TaskSceneAnchor("midas_title.png", threshold=0.86, roi=TITLE_ROI),
        TaskSceneAnchor("reward_title.png", threshold=0.86, roi=REWARD_TITLE_ROI),
    )

    def execute(self) -> str:
        completed = []
        result_message = ""
        task_error: Optional[BotError] = None
        close_error: Optional[BotError] = None

        try:
            completed = self._execute_allowed_buttons()

            if not completed:
                result_message = "no active Midas button found; dialog closed"
            else:
                result_message = "Midas taps: " + ", ".join(completed)
        except BotError as exc:
            task_error = exc

        try:
            self._close_dialog()
        except BotError as exc:
            close_error = exc

        if task_error is not None:
            if close_error is not None:
                self._log(f"Midas cleanup failed after task error: {close_error}")
            raise task_error
        if close_error is not None:
            raise close_error
        return result_message

    def execute_auto(self, *, require_cooldown_after_success: bool = False) -> MidasAutoResult:
        completed = []
        try:
            completed = self._execute_allowed_buttons()
            if completed and not require_cooldown_after_success:
                return MidasAutoResult(clicked=True)

            screen = self._wait_for_non_busy_screen()
            cooldown_seconds, ocr_text, ocr_confidence = self._read_cooldown_ocr(screen)
            return MidasAutoResult(
                clicked=bool(completed),
                cooldown_seconds=cooldown_seconds,
                ocr_text=ocr_text,
                ocr_confidence=ocr_confidence,
            )
        finally:
            self._close_dialog()

    def _execute_allowed_buttons(self) -> list[str]:
        completed = []
        self._dismiss_reward_overlay_if_present()
        self._require_midas_dialog()
        for _ in range(self.MAX_ALLOWED_TAPS):
            screen = self._wait_for_non_busy_screen()
            active = self._first_active_button_on_screen(screen)
            if active is None:
                return completed
            label, match = active
            self.context.controller.tap(*match.center)
            completed.append(label)
            self._wait_for_reward_after_tap()
            self._dismiss_reward_overlay_if_present()
        raise TaskFailedError("Midas exceeded allowed tap limit while exhausting free/20/50 tiers")

    def _read_cooldown_ocr(self, screen) -> tuple[Optional[int], str, float]:
        x, y, w, h = self.COOLDOWN_OCR_ROI
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return None, "", 0.0

        enlarged = cv2.resize(crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        padded = cv2.copyMakeBorder(
            enlarged,
            12,
            12,
            12,
            12,
            cv2.BORDER_CONSTANT,
            value=(20, 20, 35),
        )
        try:
            results = self._get_cooldown_ocr_reader().readtext(
                padded,
                detail=1,
                allowlist="0123456789:",
            )
        except Exception as exc:
            self._log(f"Midas cooldown OCR error: {exc}")
            return None, "", 0.0

        pieces = []
        for box, text, confidence in results:
            xs = [float(point[0]) for point in box]
            pieces.append((min(xs), str(text).strip(), float(confidence)))
        pieces.sort(key=lambda item: item[0])
        ocr_text = "".join(piece[1] for piece in pieces).replace(" ", "")
        confidence = min((piece[2] for piece in pieces), default=0.0)
        seconds = self._parse_cooldown_seconds(ocr_text, confidence)
        return seconds, ocr_text, confidence

    @classmethod
    def _parse_cooldown_seconds(cls, text: str, confidence: float) -> Optional[int]:
        if confidence <= cls.COOLDOWN_OCR_MIN_CONFIDENCE:
            return None
        match = re.fullmatch(r"(\d{2}):([0-5]\d):([0-5]\d)", text)
        if match is None:
            return None
        hours, minutes, seconds = (int(value) for value in match.groups())
        total = hours * 3600 + minutes * 60 + seconds
        if total >= cls.COOLDOWN_MAX_SECONDS:
            return None
        return total

    def _get_cooldown_ocr_reader(self):
        from src.ocr_utils import get_cached_easyocr_reader

        return get_cached_easyocr_reader(("en",), download_enabled=False)

    def _execute_and_return(self, started: float) -> TaskRunResult:
        result = self.execute_from_current_scene()
        # Midas is considered finished after tapping the dialog X. Keep this disabled for now
        # because returning to Daily Tasks from this point can stall or mis-size the next screen.
        # try:
        #     self.context.navigator.return_to_daily_tasks()
        # except BotError as exc:
        #     return self._result(
        #         TaskState.FAILED,
        #         f"Task action finished but return_to_daily_tasks failed: {exc}",
        #         started,
        #     )
        return self._result(TaskState.COMPLETED, result or "completed", started)

    def _allowed_buttons(self):
        return (
            ("free", "free_button.png", self.FREE_BUTTON_ROI),
            ("20-gem", "gem_20_button.png", self.GEM_20_BUTTON_ROI),
            ("50-gem", "gem_50_button.png", self.GEM_50_BUTTON_ROI),
        )

    def _first_active_button_on_screen(self, screen) -> Optional[tuple[str, MatchResult]]:
        for label, asset_name, roi in self._allowed_buttons():
            match = self.context.matcher.match_template(
                screen,
                self.asset_path(asset_name),
                threshold=self.ACTIVE_BUTTON_THRESHOLD,
                roi=roi,
            )
            if match is not None:
                return label, match
        return None

    def _wait_for_non_busy_screen(self):
        deadline = time.time() + self.BUSY_WAIT_MAX_SECONDS
        busy_logged = False
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            if not self._is_busy_overlay(screen):
                if busy_logged:
                    self._log("Midas busy overlay cleared")
                return screen
            if not busy_logged:
                self._log("Midas busy overlay detected before button scan; waiting")
                busy_logged = True
            time.sleep(1.0)
        raise TaskFailedError("Midas busy overlay did not clear before button scan")

    def _wait_for_reward_after_tap(self) -> None:
        deadline = time.time() + self.REWARD_WAIT_SECONDS
        busy_started: Optional[float] = None
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            if self._is_busy_overlay(screen):
                if busy_started is None:
                    busy_started = time.time()
                    self._log("Midas busy overlay detected after tapping allowed button; waiting")
                if time.time() - busy_started > self.BUSY_WAIT_MAX_SECONDS:
                    raise TaskFailedError("Midas busy overlay did not clear after tapping allowed button")
                deadline += self.STATE_POLL_SECONDS
                time.sleep(self.STATE_POLL_SECONDS)
                continue
            if busy_started is not None:
                self._log(f"Midas busy overlay cleared after {time.time() - busy_started:.1f}s")
                busy_started = None
            reward = self.context.matcher.match_template(
                screen,
                self.asset_path("reward_title.png"),
                threshold=0.86,
                roi=self.REWARD_TITLE_ROI,
            )
            if reward is not None:
                return
            time.sleep(self.STATE_POLL_SECONDS)
        raise TaskFailedError("Midas reward overlay did not appear after tapping allowed button")

    def _tap_if_active(self, label: str, asset_name: str, roi: Roi) -> bool:
        match = self._match_task_asset(
            asset_name,
            roi=roi,
            threshold=self.ACTIVE_BUTTON_THRESHOLD,
            timeout_seconds=1.0,
        )
        if match is None:
            return False
        self.context.controller.tap(*match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)
        return True

    def _dismiss_reward_overlay_if_present(self) -> None:
        if not self._match_task_asset(
            "reward_title.png",
            roi=self.REWARD_TITLE_ROI,
            threshold=0.86,
            timeout_seconds=0.6,
        ):
            return

        self.dismiss_reward_overlay_by_blank_taps(
            is_closed=lambda: self._match_task_asset(
                "reward_title.png",
                roi=self.REWARD_TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.4,
            )
            is None,
            max_taps=2,
            failure_message="Midas reward overlay did not close after two blank-area taps",
        )

    def _close_dialog(self) -> None:
        self._dismiss_reward_overlay_if_present()
        self._tap_close_until_gone()

    def _tap_close_until_gone(self, *, max_taps: int = 4) -> None:
        tapped = False
        for _ in range(max_taps):
            match = self._match_task_asset(
                "midas_close_button.png",
                roi=self.CLOSE_BUTTON_ROI,
                threshold=0.86,
                timeout_seconds=0.6,
            )
            if match is None:
                return
            tapped = True
            self.context.controller.tap(*match.center)
            time.sleep(TRANSITION_WAIT_SECONDS)

        if self._match_task_asset(
            "midas_close_button.png",
            roi=self.CLOSE_BUTTON_ROI,
            threshold=0.86,
            timeout_seconds=0.6,
        ):
            raise TaskFailedError("Midas close button did not disappear after repeated close taps")
        if tapped:
            return

    def _require_midas_dialog(self) -> MatchResult:
        return self._require_task_asset(
            "Midas dialog",
            "midas_title.png",
            roi=self.TITLE_ROI,
            threshold=0.86,
        )

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
        match, best = self._match_task_asset_with_best(
            asset_name,
            roi=roi,
            threshold=threshold,
            timeout_seconds=timeout_seconds,
        )
        if match is None:
            detail = self._format_best_match_detail(asset_name, threshold, roi, best)
            raise TaskFailedError(f"Midas expected screen element not found: {label}; {detail}")
        return match

    def _match_task_asset(
        self,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
    ) -> Optional[MatchResult]:
        match, _best = self._match_task_asset_with_best(
            asset_name,
            roi=roi,
            threshold=threshold,
            timeout_seconds=timeout_seconds,
        )
        return match

    def _match_task_asset_with_best(
        self,
        asset_name: str,
        *,
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
    ) -> tuple[Optional[MatchResult], Optional[MatchResult]]:
        path = self.asset_path(asset_name)
        deadline = time.time() + timeout_seconds
        best: Optional[MatchResult] = None
        busy_waited = 0.0
        busy_logged = False
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            if self._is_busy_overlay(screen):
                if not busy_logged:
                    self._log(f"Midas busy overlay detected while waiting for {asset_name}; waiting")
                    busy_logged = True
                wait_seconds = 1.5
                time.sleep(wait_seconds)
                if busy_waited < self.BUSY_WAIT_MAX_SECONDS:
                    deadline += wait_seconds
                    busy_waited += wait_seconds
                continue
            if busy_logged:
                self._log(f"Midas busy overlay cleared after {busy_waited:.1f}s")
                busy_logged = False

            match = self.context.matcher.match_template(screen, path, threshold=threshold, roi=roi)
            if match is not None:
                return match, best
            probe = self.context.matcher.best_template_match(screen, path, roi=roi)
            if probe is not None and (best is None or probe.confidence > best.confidence):
                best = probe
            time.sleep(0.35)
        return None, best

    def _is_busy_overlay(self, screen) -> bool:
        path = SHARED_ASSETS_DIR / "busy_waiting_overlay.png"
        if not path.exists():
            return False
        return self.context.matcher.match_template(
            screen,
            path,
            threshold=self.BUSY_OVERLAY_THRESHOLD,
            roi=self.BUSY_OVERLAY_ROI,
            check_brightness=False,
        ) is not None

    def _log(self, message: str) -> None:
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.log(message, force=True)

    @staticmethod
    def _format_best_match_detail(
        asset_name: str,
        threshold: float,
        roi: Optional[Roi],
        best: Optional[MatchResult],
    ) -> str:
        roi_text = "full screen" if roi is None else f"roi={roi}"
        if best is None:
            return f"template={asset_name} best_confidence=None threshold={threshold:.3f} {roi_text}"
        brightness = (
            " brightness_ratio=None"
            if best.brightness_ratio is None
            else f" brightness_ratio={best.brightness_ratio:.3f}"
        )
        return (
            f"template={asset_name} best_confidence={best.confidence:.3f} "
            f"threshold={threshold:.3f}{brightness} center={best.center} bbox={best.bbox} {roi_text}"
        )
