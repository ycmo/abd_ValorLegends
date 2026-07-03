from __future__ import annotations

from datetime import datetime
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Optional

import cv2
import numpy as np

from src.config import LOG_DIR, ROOT_DIR, TAP_COOLDOWN_SECONDS, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import BotError, TaskFailedError, TaskSkippedError
from src.account_state import DEFAULT_ACCOUNT_STATE_FILE, read_current_account
from src.ocr_utils import extract_arena_powers_easyocr, extract_arena_powers_easyocr_batch
from src.scene_detector import Scene
from src.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult, Roi, write_image


@dataclass(frozen=True)
class ArenaSettings:
    mode: str = "daily"
    max_power_k: int = 6500
    target_fights: Optional[int] = 8
    ticket_floor: Optional[int] = None
    refresh_on_no_safe_opponents: bool = False
    max_refreshes: int = 0
    max_rounds: int = 5
    account: str = "default"


_ARENA_MODE_OVERRIDE: Optional[str] = None


def set_arena_mode_override(mode: Optional[str]) -> None:
    global _ARENA_MODE_OVERRIDE
    _ARENA_MODE_OVERRIDE = mode


class ArenaTask(BaseTask):
    spec = TASK_SPECS["arena"]
    required_assets = (
        "task_label.png",
        "arena_main_anchor.png",
        "opponent_list_anchor.png",
        "multi_challenge_button.png",
        "challenge_button.png",
        "continue_button.png",
        "refresh_button.png",
        "arena_back_button.png",
    )

    MAX_POWER_K = 6500
    TARGET_FIGHTS = 8
    MAX_ROUNDS = 5
    OCR_MIN_CONFIDENCE = 0.60
    OCR_LOW_POWER_SAFE_MAX_K = 1000
    OCR_LOW_POWER_MIN_CONFIDENCE = 0.50
    OCR_OVERPOWERED_MIN_CONFIDENCE = 0.50
    OCR_UNSCALED_POWER_SAFE_MAX_K = 1000
    TICKET_OCR_MIN_CONFIDENCE = 0.60
    TICKET_OCR_CLEAR_ABOVE_FLOOR_MIN_CONFIDENCE = 0.50
    TICKET_OCR_CLEAR_ABOVE_FLOOR_MARGIN = 50
    TICKET_OCR_ATTEMPTS = 5
    TICKET_OCR_RETRY_SECONDS = 1.0

    ARENA_MAIN_ROI: Roi = (760, 0, 200, 105)
    OPPONENT_LIST_ROI: Roi = (760, 0, 160, 120)
    MULTI_CHALLENGE_ROI: Roi = (430, 455, 230, 80)
    ACTION_BUTTON_ROI: Roi = (680, 420, 220, 85)
    REFRESH_BUTTON_ROI: Roi = (540, 420, 170, 85)
    CONTINUE_BUTTON_ROI: Roi = (380, 470, 210, 70)
    BACK_BUTTON_ROI: Roi = (0, 0, 100, 90)
    TICKET_COUNT_ROI: Roi = (536, 12, 56, 30)
    OPPONENT_LIST_CLOSE_POINT = (846, 70)
    task_scene_anchors = (
        TaskSceneAnchor("arena_main_anchor.png", threshold=0.84, roi=ARENA_MAIN_ROI),
        TaskSceneAnchor("opponent_list_anchor.png", threshold=0.84, roi=OPPONENT_LIST_ROI),
    )

    CHECKBOX_X = (436, 812)
    CHECKBOX_Y = (147, 223, 299, 375)
    OPPONENT_SLOT_COUNT = len(CHECKBOX_X) * len(CHECKBOX_Y)
    CHECKED_GREEN_RATIO = 0.08
    UNCHECKED_GREEN_RATIO = 0.02

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None
        self.settings = load_arena_settings()
        self._cached_selected_opponents: list[tuple[int, int]] = []

    def execute(self) -> str:
        total_fought = 0
        rounds = 0
        refreshes = 0
        while self._should_continue(total_fought):
            rounds += 1
            if rounds > self.settings.max_rounds:
                raise TaskFailedError(
                    f"Arena exceeded {self.settings.max_rounds} rounds in mode={self.settings.mode}"
                )

            self._open_opponent_list()
            round_fights = self._uncheck_overpowered_and_start(refreshes=refreshes)
            if round_fights <= 0:
                refreshes += 1
                continue
            total_fought += round_fights
            self._wait_for_battle_result_and_continue()
            self._wait_for_arena_main("after battle result")

        self._return_to_daily_tasks()
        message = f"Arena fights: {total_fought} across {rounds} round(s)"
        if self.settings.mode != "daily":
            message += f"; mode={self.settings.mode}; refreshes={refreshes}"
        return message

    def _should_continue(self, total_fought: int) -> bool:
        if self.settings.ticket_floor is not None and self._ticket_count_at_or_below_floor():
            return False
        target = self.settings.target_fights
        if target is not None:
            return total_fought < target
        return True

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

    def _uncheck_overpowered_and_start(self, *, refreshes: int = 0) -> int:
        screen = self._require_opponent_list_screen()
        full_cached_count = self._try_start_full_cached_selection()
        if full_cached_count > 0:
            return full_cached_count

        opponents = self._read_opponents(screen)
        cached_safe_positions = self._valid_cached_selected_positions(screen)

        for opponent in opponents:
            position = (opponent["row"], opponent["col"])
            if position in cached_safe_positions:
                continue
            if opponent["power_k"] <= self.settings.max_power_k:
                continue
            state = self._checkbox_state(screen, opponent["row"], opponent["col"])
            if state == "checked":
                self.context.controller.tap(*self._checkbox_center(opponent["row"], opponent["col"]))
                time.sleep(TAP_COOLDOWN_SECONDS)
                screen = self._require_opponent_list_screen()
                if self._checkbox_state(screen, opponent["row"], opponent["col"]) != "unchecked":
                    self._skip_current_opponent_list(
                        screen,
                        "Arena failed to verify over-7000k opponent was unchecked: "
                        f"row={opponent['row']} col={opponent['col']} power={opponent['power_text']}",
                    )
            elif state != "unchecked":
                self._skip_current_opponent_list(
                    screen,
                    "Arena checkbox state is uncertain for over-7000k opponent: "
                    f"row={opponent['row']} col={opponent['col']} power={opponent['power_text']}",
                )

        screen = self._require_opponent_list_screen()
        try:
            selected_positions = self._checked_opponent_positions(screen)
        except TaskFailedError as exc:
            self._skip_current_opponent_list(screen, str(exc))
        selected_count = len(selected_positions)
        if selected_count <= 0:
            if self.settings.refresh_on_no_safe_opponents and refreshes < self.settings.max_refreshes:
                self._cached_selected_opponents = []
                self._refresh_opponent_list()
                return 0
            self._skip_current_opponent_list(
                screen,
                f"Arena has no checked safe opponents after filtering over-{self.settings.max_power_k}k targets",
            )

        self._tap_task_asset(
            "start Arena challenge",
            "challenge_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._cached_selected_opponents = selected_positions
        return selected_count

    def _try_start_full_cached_selection(self) -> int:
        if len(self._cached_selected_opponents) != self.OPPONENT_SLOT_COUNT:
            return 0
        self._log("Arena reusing full checked opponent page without OCR")
        self._tap_task_asset(
            "start Arena challenge",
            "challenge_button.png",
            roi=self.ACTION_BUTTON_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        return self.OPPONENT_SLOT_COUNT

    def _valid_cached_selected_positions(self, screen) -> set[tuple[int, int]]:
        if not self._cached_selected_opponents:
            return set()
        positions = set()
        for row, col in self._cached_selected_opponents:
            if self._checkbox_state(screen, row, col) != "checked":
                self._cached_selected_opponents = []
                return set()
            positions.add((row, col))
        self._log(f"Arena reusing safe checked opponent positions: {sorted(positions)}")
        return positions

    def _refresh_opponent_list(self) -> None:
        self._tap_task_asset(
            "refresh Arena opponent list",
            "refresh_button.png",
            roi=self.REFRESH_BUTTON_ROI,
            threshold=0.86,
            wait_after_seconds=TRANSITION_WAIT_SECONDS,
        )
        self._require_task_asset(
            "Arena opponent list after refresh",
            "opponent_list_anchor.png",
            roi=self.OPPONENT_LIST_ROI,
            threshold=0.84,
            timeout_seconds=6.0,
        )

    def _read_opponents(self, screen) -> list[dict]:
        reader = self._get_ocr_reader()
        opponents = extract_arena_powers_easyocr_batch(screen, reader=reader)
        uncertain = self._uncertain_ocr_items(opponents)
        if uncertain:
            opponents = extract_arena_powers_easyocr(screen, reader=reader)
            uncertain = self._uncertain_ocr_items(opponents)
        if uncertain:
            detail = "; ".join(
                f"row={item['row']} col={item['col']} text={item['power_text']!r} "
                f"conf={item.get('confidence', 0.0):.3f}"
                for item in uncertain
            )
            self._skip_current_opponent_list(
                screen,
                f"Arena OCR is uncertain; stopping before selecting opponents: {detail}",
            )
        return opponents

    def _uncertain_ocr_items(self, opponents: list[dict]) -> list[dict]:
        return [item for item in opponents if not self._is_ocr_power_confident_enough(item)]

    def _is_ocr_power_confident_enough(self, item: dict) -> bool:
        power_k = item["power_k"]
        confidence = item.get("confidence", 0.0)
        if power_k < 0:
            return False
        if not item.get("has_scale_suffix", True) and power_k <= self.OCR_UNSCALED_POWER_SAFE_MAX_K:
            return True
        if confidence >= self.OCR_MIN_CONFIDENCE:
            return True
        if power_k > self.settings.max_power_k and confidence >= self.OCR_OVERPOWERED_MIN_CONFIDENCE:
            return True
        if power_k <= self.OCR_LOW_POWER_SAFE_MAX_K and confidence >= self.OCR_LOW_POWER_MIN_CONFIDENCE:
            return True
        return False

    def _ticket_count_at_or_below_floor(self) -> bool:
        floor = self.settings.ticket_floor
        if floor is None:
            return False
        last_screen = None
        last_confidence = 0.0
        for attempt in range(1, self.TICKET_OCR_ATTEMPTS + 1):
            screen = self.context.controller.screenshot()
            last_screen = screen
            if not self.context.matcher.match_template(
                screen,
                self.asset_path("arena_main_anchor.png"),
                threshold=0.84,
                roi=self.ARENA_MAIN_ROI,
            ):
                return False
            value, confidence = self._read_ticket_count(screen)
            last_confidence = confidence
            if value is not None and self._is_ticket_count_confident_enough(value, confidence, floor):
                self._log(
                    f"Arena tickets={value} confidence={confidence:.3f}; floor={floor}; mode={self.settings.mode}"
                )
                return value <= floor
            value_text = "unknown" if value is None else str(value)
            self._log(
                f"Arena ticket OCR uncertain attempt={attempt}/{self.TICKET_OCR_ATTEMPTS} "
                f"value={value_text} confidence={confidence:.3f}; retrying"
            )
            time.sleep(self.TICKET_OCR_RETRY_SECONDS)
        debug_path = None
        if last_screen is not None:
            debug_path = self._save_ticket_ocr_uncertain_debug(last_screen, last_confidence)
        message = "Arena ticket count OCR is uncertain; stopping before long-run fight"
        if debug_path is not None:
            message += f"; saved_screenshot={debug_path}"
        raise TaskFailedError(message)

    def _is_ticket_count_confident_enough(self, value: int, confidence: float, floor: int) -> bool:
        if confidence >= self.TICKET_OCR_MIN_CONFIDENCE:
            return True
        if value >= floor + self.TICKET_OCR_CLEAR_ABOVE_FLOOR_MARGIN:
            return confidence >= self.TICKET_OCR_CLEAR_ABOVE_FLOOR_MIN_CONFIDENCE
        return False

    def _save_ticket_ocr_uncertain_debug(self, screen, confidence: float) -> str:
        filename = datetime.now().strftime("arena_ticket_ocr_uncertain_%Y%m%d_%H%M%S_%f.png")
        raw_path = LOG_DIR / filename
        saved_path = str(write_image(raw_path, screen))
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is not None:
            x, y, w, h = self.TICKET_COUNT_ROI
            save_debug(
                "arena_ticket_ocr_uncertain",
                screen,
                lines=[
                    "Arena ticket OCR uncertain",
                    f"confidence={confidence:.3f}",
                    f"mode={self.settings.mode}",
                    f"floor={self.settings.ticket_floor}",
                    f"raw={saved_path}",
                ],
                boxes=[(x, y, w, h, "ticket_count_roi")],
            )
        return saved_path

    def _read_ticket_count(self, screen) -> tuple[Optional[int], float]:
        x, y, w, h = self.TICKET_COUNT_ROI
        roi = screen[y : y + h, x : x + w]
        if roi.size == 0:
            return None, 0.0
        prepared = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        prepared = cv2.copyMakeBorder(
            prepared,
            12,
            12,
            12,
            12,
            cv2.BORDER_CONSTANT,
            value=[255, 255, 255],
        )
        try:
            results = self._get_ocr_reader().readtext(prepared, detail=1, allowlist="0123456789")
        except TypeError:
            results = self._get_ocr_reader().readtext(prepared, allowlist="0123456789")
        pieces = []
        for box, text, confidence in results:
            digits = "".join(char for char in str(text) if char.isdigit())
            if not digits:
                continue
            left_values = []
            for point in box:
                try:
                    left_values.append(float(point[0]))
                except (TypeError, ValueError, IndexError):
                    continue
            pieces.append((min(left_values) if left_values else 0.0, digits, float(confidence)))
        if not pieces:
            return None, 0.0
        pieces.sort(key=lambda item: item[0])
        digits = "".join(piece[1] for piece in pieces)
        confidence = min(piece[2] for piece in pieces)
        return int(digits), confidence

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

    def _skip_current_opponent_list(self, screen, reason: str) -> NoReturn:
        screenshot_path = self._save_uncertain_screenshot(screen)
        print(f"saved_screenshot={screenshot_path}", flush=True)
        try:
            self._return_from_opponent_list_to_daily_tasks()
        except BotError as exc:
            raise TaskFailedError(
                f"{reason}; saved_screenshot={screenshot_path}; safe return failed: {exc}"
            ) from exc
        raise TaskSkippedError(f"{reason}; saved_screenshot={screenshot_path}")

    def _save_uncertain_screenshot(self, screen) -> str:
        filename = datetime.now().strftime("arena_uncertain_%Y%m%d_%H%M%S_%f.png")
        path = LOG_DIR / filename
        return str(write_image(path, screen))

    def _return_from_opponent_list_to_daily_tasks(self) -> None:
        self.context.controller.tap(*self.OPPONENT_LIST_CLOSE_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

        if self._is_daily_tasks_visible():
            return
        if not self._match_task_asset(
            "arena_main_anchor.png",
            roi=self.ARENA_MAIN_ROI,
            threshold=0.84,
            timeout_seconds=3.0,
        ):
            raise TaskFailedError("Arena opponent list did not close after tapping top-right X")
        self._return_to_daily_tasks()

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
        return len(self._checked_opponent_positions(screen))

    def _checked_opponent_positions(self, screen) -> list[tuple[int, int]]:
        positions = []
        for row in range(1, 5):
            for col in range(1, 3):
                state = self._checkbox_state(screen, row, col)
                if state == "checked":
                    positions.append((row, col))
                elif state == "unknown":
                    raise TaskFailedError(f"Arena checkbox state is uncertain: row={row} col={col}")
        return positions

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
            from src.ocr_utils import get_cached_easyocr_reader

            self._ocr_reader = get_cached_easyocr_reader(("en",), download_enabled=False)
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


def load_arena_settings(path: Path = ROOT_DIR / "config" / "arena.jsonc") -> ArenaSettings:
    mode = _ARENA_MODE_OVERRIDE
    data = {}
    if path.exists():
        data = json.loads(_strip_jsonc_comments(path.read_text(encoding="utf-8")))
    if not mode:
        mode = str(data.get("mode") or "daily")

    modes = data.get("modes") if isinstance(data.get("modes"), dict) else {}
    mode_config = modes.get(mode)
    if not isinstance(mode_config, dict):
        mode = "daily"
        mode_config = modes.get("daily") if isinstance(modes.get("daily"), dict) else {}

    account = _read_active_account(data.get("active_account_file"))
    accounts = data.get("accounts") if isinstance(data.get("accounts"), dict) else {}
    account_config = accounts.get(account) if isinstance(accounts.get(account), dict) else {}
    default_account_config = accounts.get("default") if isinstance(accounts.get("default"), dict) else {}

    max_power_k = int(account_config.get("max_power_k", default_account_config.get("max_power_k", ArenaTask.MAX_POWER_K)))
    return ArenaSettings(
        mode=mode,
        max_power_k=max_power_k,
        target_fights=_optional_int(mode_config.get("target_fights", ArenaTask.TARGET_FIGHTS)),
        ticket_floor=_optional_int(mode_config.get("ticket_floor")),
        refresh_on_no_safe_opponents=bool(data.get("refresh_on_no_safe_opponents", True)),
        max_refreshes=int(data.get("max_refreshes", 10) or 0),
        max_rounds=int(mode_config.get("max_rounds", ArenaTask.MAX_ROUNDS) or ArenaTask.MAX_ROUNDS),
        account=account,
    )


def _read_active_account(path_value) -> str:
    path = Path(path_value) if path_value else DEFAULT_ACCOUNT_STATE_FILE
    if not path.is_absolute():
        path = ROOT_DIR / path
    return read_current_account(path=path, default="default")


def _optional_int(value) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _strip_jsonc_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        in_string = False
        escaped = False
        keep = []
        index = 0
        while index < len(line):
            char = line[index]
            next_char = line[index + 1] if index + 1 < len(line) else ""
            if escaped:
                keep.append(char)
                escaped = False
            elif char == "\\" and in_string:
                keep.append(char)
                escaped = True
            elif char == '"':
                keep.append(char)
                in_string = not in_string
            elif char == "/" and next_char == "/" and not in_string:
                break
            else:
                keep.append(char)
            index += 1
        lines.append("".join(keep))
    return "\n".join(lines)
