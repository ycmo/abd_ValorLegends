from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2

from src.config import CAPTURES_DIR, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src.ocr_utils import build_easyocr_reader, parse_power_value
from src.task_runner import BaseTask, TaskRunResult, TaskSceneAnchor, TaskState
from src.vision_matcher import MatchResult, Roi, write_image


@dataclass(frozen=True)
class AbyssRentalRow:
    scan_index: int
    row_index: int
    row_y: int
    power_text: str
    power_k: int
    confidence: float
    rent_available: bool
    rent_center: Optional[tuple[int, int]]
    rent_confidence: float
    rent_brightness_ratio: Optional[float]
    crop_path: Path


class AbyssTask(BaseTask):
    spec = TASK_SPECS["abyss"]
    required_assets = (
        "rental_entry_button.png",
        "forest_tab.png",
        "dragon_hero.png",
        "rent_button.png",
        "rented_button.png",
        "training_button.png",
        "start_training_button.png",
        "artifact_plan_1.png",
        "artifact_plan_2.png",
        "artifact_tab_2.png",
        "confirm_button.png",
        "skip_button.png",
        "keep_result_button.png",
        "post_keep_confirm_button.png",
        "accept_result_button.png",
        "yes_button.png",
        "exit_button.png",
        "final_done_zero.png",
        "main_done_zero.png",
    )
    task_scene_anchors = (
        TaskSceneAnchor("rental_entry_button.png", threshold=0.76, roi=(735, 455, 100, 80)),
        TaskSceneAnchor("training_button.png", threshold=0.78, roi=(860, 240, 90, 130)),
        TaskSceneAnchor("forest_tab.png", threshold=0.40, roi=(470, 437, 74, 59)),
        TaskSceneAnchor("start_training_button.png", threshold=0.78, roi=(820, 420, 130, 110)),
    )

    RENT_ENTRY_POINT = (782, 491)
    RENT_ENTRY_ROI: Roi = (735, 455, 100, 80)
    RENT_ENTRY_THRESHOLD = 0.76
    RENT_ENTRY_WAIT_SECONDS = 18.0
    RENTAL_VIEW_WAIT_SECONDS = 8.0
    MAIN_DONE_ZERO_ROI: Roi = (900, 430, 55, 45)
    MAIN_DONE_ZERO_THRESHOLD = 0.88
    TRAINING_ENTRY_WAIT_SECONDS = 10.0
    FORMATION_WAIT_SECONDS = 10.0
    FOREST_TAB_POINT = (507, 466)
    TRAINING_ENTRY_POINT = (912, 318)
    RENTED_HERO_POINT = (55, 482)
    ARTIFACT_PLAN_POINT = (914, 286)
    ARTIFACT_TAB_2_POINT = (622, 115)
    UNIFY_ARTIFACT_POINT = (769, 397)
    YES_POINT = (588, 402)
    KEEP_RESULT_POINT = (366, 480)

    FOREST_TAB_ROI: Roi = (470, 437, 74, 59)
    RENT_BUTTON_ROI: Roi = (650, 100, 190, 380)
    POWER_ROW_X = 378
    POWER_ROW_W = 135
    POWER_ROW_H = 34
    RENTAL_ROW_Y = (139, 237, 335, 433)
    RENTAL_ROW_TOLERANCE = 32
    RENTAL_SWIPES = 5
    RENT_BUTTON_ACTIVE_MIN_CONFIDENCE = 0.78
    RENT_BUTTON_ACTIVE_MIN_BRIGHTNESS = 0.92
    RENTAL_POWER_MIN_CONFIDENCE = 0.60
    RENTED_SKIP_THRESHOLD = 3
    DRAGON_HERO_THRESHOLD = 0.75
    DRAGON_HERO_ROI_X = 295
    DRAGON_HERO_ROI_W = 85
    DRAGON_HERO_ROI_H = 82
    RENTAL_REVERSE_SEARCH_ATTEMPTS = 14

    ARTIFACT_BUTTON_ROI: Roi = (875, 235, 80, 130)
    ARTIFACT_PLAN_1_THRESHOLD = 0.64
    ARTIFACT_PLAN_2_THRESHOLD = 0.82
    ARTIFACT_PLAN_CONFIDENCE_MARGIN = 0.05
    ARTIFACT_TAB_ROI: Roi = (515, 85, 230, 60)
    CONFIRM_ROI: Roi = (390, 430, 180, 70)
    SKIP_ROI: Roi = (870, 55, 90, 80)
    KEEP_RESULT_ROI: Roi = (270, 435, 190, 80)
    POST_KEEP_CONFIRM_ROI: Roi = (500, 350, 180, 90)
    ACCEPT_RESULT_ROI: Roi = (270, 435, 200, 80)
    YES_BUTTON_ROI: Roi = (500, 350, 180, 90)
    EXIT_BUTTON_ROI: Roi = (500, 430, 180, 90)
    FINAL_DONE_STATUS_ROI: Roi = (393, 466, 40, 26)
    FINAL_DONE_STATUS_THRESHOLD = 0.90
    POST_RESULT_TIMEOUT_SECONDS = 180.0
    POST_RESULT_MAX_TAPS = 30
    POST_RESULT_WAIT_SECONDS = 6.0
    EXIT_RESULT_MAX_TAPS = 5

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None
        self._last_rental_scan_active_count = 0
        self._last_rental_scan_rented_count = 0
        self._last_rental_scan_dragon_count = 0

    def run(self) -> TaskRunResult:
        started = time.time()
        missing = self.missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(p) for p in missing),
                started,
            )

        try:
            return self._result(TaskState.COMPLETED, self.execute(), started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except (BotError, TaskFailedError) as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def execute(self) -> str:
        if self._is_main_done_zero():
            raise TaskSkippedError("abyss already completed: main_done_zero.png matched 0/2")

        rental_message = "rental not attempted"
        self._tap_rental_entry()
        rows = self.probe_rental_scan(tap_forest=True)
        best = self._best_available_rental(rows)
        if best is None:
            if self._rental_scan_indicates_already_rented():
                self._log("Abyss rental skipped: rented buttons found and no active rent button")
                rental_message = "rental skipped: already rented"
            elif self._rental_scan_indicates_no_dragon_candidate():
                self._log(
                    "Abyss rental skipped: active rent buttons found but no dragon candidate "
                    f"active={self._last_rental_scan_active_count}"
                )
                rental_message = "rental skipped: no dragon candidate"
            else:
                raise TaskFailedError("Abyss rental scan found no rentable hero with readable power")
        else:
            self._log(
                "Abyss rental best candidate "
                f"scan={best.scan_index} row={best.row_index} power={best.power_text} "
                f"power_k={best.power_k} confidence={best.confidence:.3f}"
            )
            self._find_and_tap_rental_candidate_by_reverse_search(best)
            rental_message = f"rented scan={best.scan_index} row={best.row_index} power={best.power_text}"
            time.sleep(TRANSITION_WAIT_SECONDS)
        self._close_rental_dialog()
        time.sleep(TRANSITION_WAIT_SECONDS)

        self._tap_training_entry()
        self._tap_rented_hero()
        self._ensure_artifact_plan_2()
        self._tap_start_training()
        self._wait_skip_and_keep_result()
        return f"abyss one round completed; {rental_message}"

    def _is_main_done_zero(self) -> bool:
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("main_done_zero.png"),
            threshold=self.MAIN_DONE_ZERO_THRESHOLD,
            roi=self.MAIN_DONE_ZERO_ROI,
            check_brightness=False,
        )
        if match is None:
            probe = self.context.matcher.best_template_match(
                screen,
                self.asset_path("main_done_zero.png"),
                roi=self.MAIN_DONE_ZERO_ROI,
            )
            best_text = "none" if probe is None else f"{probe.confidence:.3f}"
            self._log(f"Abyss main done check not matched; template=main_done_zero.png best_confidence={best_text}")
            return False

        self._log(f"Abyss already completed; template=main_done_zero.png confidence={match.confidence:.3f}")
        self._save_abyss_debug(
            "abyss_main_done_zero",
            screen,
            lines=[
                "Abyss already completed on main screen",
                f"template=main_done_zero.png confidence={match.confidence:.3f} threshold={self.MAIN_DONE_ZERO_THRESHOLD:.3f}",
            ],
            boxes=[(*self.MAIN_DONE_ZERO_ROI, "done_status"), (*match.bbox, "go")],
        )
        return True

    def probe_rental_scan(self, *, tap_forest: bool = True) -> list[AbyssRentalRow]:
        if tap_forest:
            self._tap_forest_if_visible()

        debug_dir = CAPTURES_DIR / "action_debug" / f"abyss_rental_scan_{time.strftime('%Y%m%d_%H%M%S')}"
        self._last_rental_scan_active_count = 0
        self._last_rental_scan_rented_count = 0
        self._last_rental_scan_dragon_count = 0
        rows: list[AbyssRentalRow] = []
        for scan_index in range(1, self.RENTAL_SWIPES + 1):
            screen = self.context.controller.screenshot()
            rows.extend(self._scan_rental_view(screen, scan_index, debug_dir))
            if scan_index < self.RENTAL_SWIPES:
                self._swipe_rental_list()

        self._save_rental_probe_summary(rows, debug_dir)
        return rows

    def _scan_rental_view(self, screen, scan_index: int, debug_dir: Path) -> list[AbyssRentalRow]:
        rent_matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("rent_button.png"),
            threshold=0.78,
            roi=self.RENT_BUTTON_ROI,
            check_brightness=False,
            min_center_distance=55,
        )
        rented_matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("rented_button.png"),
            threshold=0.78,
            roi=self.RENT_BUTTON_ROI,
            check_brightness=False,
            min_center_distance=55,
        )
        found_rows: list[AbyssRentalRow] = []
        row_targets = self._rental_row_targets(rent_matches, rented_matches)
        for row_index, row_y, rent_match, rent_status in row_targets:
            if rent_status == "active":
                self._last_rental_scan_active_count += 1
            elif rent_status == "rented":
                self._last_rental_scan_rented_count += 1
            if rent_status != "active":
                continue
            if not self._is_dragon_rental_row(screen, row_y):
                continue
            self._last_rental_scan_dragon_count += 1
            power_roi = self._power_roi_for_row(row_y)
            power_text, confidence, crop_path = self._read_power_ocr(screen, power_roi, debug_dir, scan_index, row_index)
            found_rows.append(
                AbyssRentalRow(
                    scan_index=scan_index,
                    row_index=row_index,
                    row_y=row_y,
                    power_text=power_text,
                    power_k=parse_power_value(power_text),
                    confidence=confidence,
                    rent_available=True,
                    rent_center=rent_match.center,
                    rent_confidence=rent_match.confidence,
                    rent_brightness_ratio=rent_match.brightness_ratio,
                    crop_path=crop_path,
                )
            )
        self._save_rental_scan_debug(screen, found_rows, rent_matches + rented_matches, debug_dir, scan_index)
        return found_rows

    def _is_dragon_rental_row(self, screen, row_y: int) -> bool:
        roi = self._dragon_roi_for_row(row_y)
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("dragon_hero.png"),
            threshold=self.DRAGON_HERO_THRESHOLD,
            roi=roi,
            check_brightness=False,
        )
        return match is not None

    def _rental_scan_indicates_already_rented(self) -> bool:
        return (
            getattr(self, "_last_rental_scan_active_count", 0) == 0
            and getattr(self, "_last_rental_scan_rented_count", 0) > self.RENTED_SKIP_THRESHOLD
        )

    def _rental_scan_indicates_no_dragon_candidate(self) -> bool:
        return (
            getattr(self, "_last_rental_scan_active_count", 0) > 0
            and getattr(self, "_last_rental_scan_dragon_count", 0) == 0
        )

    def _read_power_ocr(
        self,
        screen,
        roi: Roi,
        debug_dir: Path,
        scan_index: int,
        row_index: int,
    ) -> tuple[str, float, Path]:
        x, y, w, h = roi
        crop = screen[y : y + h, x : x + w]
        crop_path = debug_dir / f"{scan_index:02d}_{row_index:02d}_power.png"
        write_image(crop_path, crop)
        if crop.size == 0:
            return "", 0.0, crop_path

        enlarged = cv2.resize(crop, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        padded = cv2.copyMakeBorder(enlarged, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=[25, 25, 45])
        ocr_results = self._get_ocr_reader().readtext(padded, detail=1, allowlist="0123456789,")
        text, confidence = self._combine_power_ocr(ocr_results)
        return text, confidence, crop_path

    def _combine_power_ocr(self, ocr_results) -> tuple[str, float]:
        pieces = []
        for box, text, confidence in ocr_results:
            clean = re.sub(r"[^0-9,]", "", str(text))
            if not clean:
                continue
            left = min(float(point[0]) for point in box)
            pieces.append((left, clean, float(confidence)))
        if not pieces:
            return "", 0.0
        pieces.sort(key=lambda item: item[0])
        return "".join(piece[1] for piece in pieces), min(piece[2] for piece in pieces)

    def _tap_rental_entry(self) -> None:
        deadline = time.time() + self.RENT_ENTRY_WAIT_SECONDS
        last_screen = None
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            last_screen = screen
            match = self.context.matcher.match_template(
                screen,
                self.asset_path("rental_entry_button.png"),
                threshold=self.RENT_ENTRY_THRESHOLD,
                roi=self.RENT_ENTRY_ROI,
                check_brightness=False,
            )
            if match is None:
                self._log("Abyss waiting for rental entry")
                time.sleep(1.0)
                continue

            self.context.controller.annotate_next_tap_debug(
                lines=[
                    "abyss open rental",
                    f"template=rental_entry_button.png confidence={match.confidence:.3f}",
                ],
                boxes=[(*match.bbox, "go")],
            )
            self.context.controller.tap(*match.center)
            time.sleep(TRANSITION_WAIT_SECONDS)
            self._wait_for_rental_view()
            return

        self._save_abyss_debug(
            "abyss_rental_entry_missing",
            last_screen,
            lines=["Abyss rental entry not found before timeout"],
            boxes=[(*self.RENT_ENTRY_ROI, "go")],
        )
        raise TaskFailedError("Abyss rental entry not found")

    def _wait_for_rental_view(self) -> None:
        deadline = time.time() + self.RENTAL_VIEW_WAIT_SECONDS
        last_screen = None
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            last_screen = screen
            match = self.context.matcher.match_template(
                screen,
                self.asset_path("forest_tab.png"),
                threshold=0.40,
                roi=self.FOREST_TAB_ROI,
                check_brightness=False,
            )
            if match is not None:
                return
            self._log("Abyss waiting for rental view")
            time.sleep(1.0)

        self._save_abyss_debug(
            "abyss_rental_view_missing",
            last_screen,
            lines=["Abyss rental view did not appear after tapping rental entry"],
            boxes=[(*self.FOREST_TAB_ROI, "go")],
        )
        raise TaskFailedError("Abyss rental view did not open after tapping rental entry")

    def _save_abyss_debug(self, name: str, screen, *, lines: list[str], boxes: list[tuple[int, int, int, int, str]]) -> None:
        if screen is None:
            return
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is not None:
            save_debug(name, screen, lines=lines, boxes=boxes)

    def _tap_rental_entry_legacy_fixed_point(self) -> None:
        self.context.controller.annotate_next_tap_debug(
            lines=["abyss open rental"],
            boxes=[(735, 455, 95, 70, "go")],
        )
        self.context.controller.tap(*self.RENT_ENTRY_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _swipe_rental_list(self) -> None:
        self.context.controller.annotate_next_tap_debug(
            lines=["abyss rental list swipe inside power ROI column"],
            boxes=[(360, 115, 170, 360, "label_roi")],
        )
        self.context.controller.swipe(455, 430, 455, 170, duration_ms=520)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _reverse_swipe_rental_list(self) -> None:
        self.context.controller.annotate_next_tap_debug(
            lines=["abyss rental list reverse swipe to earlier page"],
            boxes=[(360, 115, 170, 360, "label_roi")],
        )
        self.context.controller.swipe(455, 190, 455, 370, duration_ms=520)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _find_and_tap_rental_candidate_by_reverse_search(self, target: AbyssRentalRow) -> None:
        debug_dir = self._rental_rescan_debug_dir()
        scanned_rows: list[AbyssRentalRow] = []
        for attempt in range(1, self.RENTAL_REVERSE_SEARCH_ATTEMPTS + 1):
            screen = self.context.controller.screenshot()
            rows = self._scan_rental_view(screen, attempt, debug_dir)
            scanned_rows.extend(rows)
            match = self._find_matching_rental_row(rows, target)
            if match is not None:
                self._save_rental_probe_summary(scanned_rows, debug_dir)
                self._tap_rental_candidate(match)
                return
            if attempt < self.RENTAL_REVERSE_SEARCH_ATTEMPTS:
                self._reverse_swipe_rental_list()
        self._save_rental_probe_summary(scanned_rows, debug_dir)
        raise TaskFailedError(f"Abyss could not relocate rental candidate power={target.power_text}")

    def _find_matching_rental_row(
        self,
        rows: list[AbyssRentalRow],
        target: AbyssRentalRow,
    ) -> Optional[AbyssRentalRow]:
        for row in rows:
            if not row.rent_available or row.rent_center is None:
                continue
            if row.power_text == target.power_text:
                return row
            if row.power_k > 0 and row.power_k == target.power_k and row.confidence >= self.RENTAL_POWER_MIN_CONFIDENCE:
                return row
        return None

    def _rental_rescan_debug_dir(self) -> Path:
        return CAPTURES_DIR / "action_debug" / f"abyss_rental_rescan_{time.strftime('%Y%m%d_%H%M%S')}"

    def _tap_rental_candidate(self, row: AbyssRentalRow) -> None:
        if row.rent_center is None:
            raise TaskFailedError("Abyss selected rental row has no rent button center")
        x, y = row.rent_center
        self.context.controller.annotate_next_tap_debug(
            lines=[
                f"abyss rent best scan={row.scan_index} row={row.row_index}",
                f"power={row.power_text} ocr_conf={row.confidence:.3f}",
            ],
            boxes=[(x - 45, y - 20, 90, 40, "go")],
        )
        self.context.controller.tap(x, y)

    def _tap_forest_if_visible(self) -> None:
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("forest_tab.png"),
            threshold=0.40,
            roi=self.FOREST_TAB_ROI,
        )
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss rental select forest tab fixed point",
                (
                    f"template=forest_tab.png confidence={match.confidence:.3f}"
                    if match
                    else "template=forest_tab.png confidence=not_found"
                ),
                f"fixed_point={self.FOREST_TAB_POINT[0]},{self.FOREST_TAB_POINT[1]}",
            ],
            boxes=[(*self.FOREST_TAB_ROI, "go")],
        )
        self.context.controller.tap(*self.FOREST_TAB_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _close_rental_dialog(self) -> None:
        for attempt in range(1, 5):
            screen = self.context.controller.screenshot()
            rental_view = self._match_rental_view(screen)
            if rental_view is None:
                return
            self.context.controller.annotate_next_tap_debug(
                lines=[
                    f"abyss close rental dialog {attempt}/4",
                    f"confirm_template=forest_tab.png confidence={rental_view.confidence:.3f}",
                    "tap=fixed rental close x",
                ],
                boxes=[(775, 35, 70, 70, "go")],
            )
            self.context.controller.tap(809, 65)
            time.sleep(TRANSITION_WAIT_SECONDS)
            self.wait_while_busy(label="Abyss rental close busy", max_seconds=20.0)
            screen = self.context.controller.screenshot()
            if self._match_rental_view(screen) is None:
                self._log(f"Abyss rental dialog closed after tap {attempt}")
                return

        screen = self.context.controller.screenshot()
        self._save_abyss_debug(
            "abyss_rental_close_failed",
            screen,
            lines=["Abyss rental dialog did not close", "template=forest_tab.png"],
            boxes=[(*self.FOREST_TAB_ROI, "go")],
        )
        raise TaskFailedError("Abyss rental dialog did not close: forest_tab.png still visible")

    def _tap_training_entry(self) -> None:
        match = self._wait_for_template(
            "training_button.png",
            threshold=0.78,
            roi=(860, 240, 90, 130),
            timeout_seconds=self.TRAINING_ENTRY_WAIT_SECONDS,
            label="Abyss training entry",
        )
        self.tap_match_until_gone(
            match,
            label="Abyss open training formation",
            threshold=0.78,
            max_taps=4,
        )
        self._wait_for_template(
            "start_training_button.png",
            threshold=0.78,
            roi=(820, 420, 130, 110),
            timeout_seconds=self.FORMATION_WAIT_SECONDS,
            label="Abyss formation start training",
        )

    def _match_rental_view(self, screen) -> Optional[MatchResult]:
        return self.context.matcher.match_template(
            screen,
            self.asset_path("forest_tab.png"),
            threshold=0.40,
            roi=self.FOREST_TAB_ROI,
            check_brightness=False,
        )

    def _wait_for_template(
        self,
        asset_name: str,
        *,
        threshold: float,
        roi: Roi,
        timeout_seconds: float,
        label: str,
    ) -> MatchResult:
        deadline = time.time() + timeout_seconds
        best: Optional[MatchResult] = None
        while time.time() < deadline:
            self.wait_while_busy(label=f"{label} busy", max_seconds=20.0)
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(
                screen,
                self.asset_path(asset_name),
                threshold=threshold,
                roi=roi,
                check_brightness=False,
            )
            if match is not None:
                return match
            probe = self.context.matcher.best_template_match(screen, self.asset_path(asset_name), roi=roi)
            if probe is not None and (best is None or probe.confidence > best.confidence):
                best = probe
            best_text = "none" if best is None else f"{best.confidence:.3f}"
            self._log(f"{label} waiting; template={asset_name} best_confidence={best_text}")
            time.sleep(0.6)

        screen = self.context.controller.screenshot()
        lines = [f"{label} template not found", f"template={asset_name}"]
        if best is not None:
            lines.append(f"best_confidence={best.confidence:.3f}")
        self._save_abyss_debug(
            f"abyss_{asset_name.removesuffix('.png')}_missing",
            screen,
            lines=lines,
            boxes=[(*roi, "go")],
        )
        best_suffix = f" best_confidence={best.confidence:.3f}" if best is not None else ""
        raise TaskFailedError(f"Abyss template not found: {asset_name}{best_suffix}")

    def _tap_rented_hero(self) -> None:
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss select rented hero fixed slot",
                "template=none fixed_slot=rented hero",
                f"fixed_point={self.RENTED_HERO_POINT[0]},{self.RENTED_HERO_POINT[1]}",
            ],
            boxes=[(18, 445, 76, 78, "go")],
        )
        self.context.controller.tap(*self.RENTED_HERO_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _ensure_artifact_plan_2(self) -> None:
        screen = self.context.controller.screenshot()
        plan_2 = self.context.matcher.match_template(
            screen,
            self.asset_path("artifact_plan_2.png"),
            threshold=self.ARTIFACT_PLAN_2_THRESHOLD,
            roi=self.ARTIFACT_BUTTON_ROI,
        )
        plan_1 = self.context.matcher.match_template(
            screen,
            self.asset_path("artifact_plan_1.png"),
            threshold=self.ARTIFACT_PLAN_1_THRESHOLD,
            roi=self.ARTIFACT_BUTTON_ROI,
        )
        self._log(
            "Abyss artifact plan check "
            f"artifact_plan_2.png={self._match_confidence_text(plan_2)} "
            f"artifact_plan_1.png={self._match_confidence_text(plan_1)}"
        )
        if self._artifact_plan_2_wins(plan_2, plan_1):
            self._log(f"Abyss artifact plan already 2 template=artifact_plan_2.png confidence={plan_2.confidence:.3f}")
            self._save_abyss_debug(
                "abyss_artifact_plan_already_2",
                screen,
                lines=[
                    "Abyss artifact plan already 2",
                    f"template=artifact_plan_2.png confidence={plan_2.confidence:.3f} threshold=0.820",
                    f"template=artifact_plan_1.png confidence={self._match_confidence_text(plan_1)} threshold=0.640",
                ],
                boxes=[(*self.ARTIFACT_BUTTON_ROI, "roi"), (*plan_2.bbox, "go")],
            )
            return

        if plan_1 is None:
            self._save_abyss_debug(
                "abyss_artifact_plan_missing",
                screen,
                lines=[
                    "Abyss artifact plan templates not recognized",
                    f"template=artifact_plan_2.png confidence={self._match_confidence_text(plan_2)} threshold=0.820",
                    "template=artifact_plan_1.png confidence=not_found threshold=0.640",
                ],
                boxes=[(*self.ARTIFACT_BUTTON_ROI, "go")],
            )
            raise TaskFailedError(
                "Abyss templates not recognized: artifact_plan_2.png, artifact_plan_1.png"
            )
        if plan_2 is not None and not self._artifact_plan_1_wins(plan_1, plan_2):
            self._save_abyss_debug(
                "abyss_artifact_plan_ambiguous",
                screen,
                lines=[
                    "Abyss artifact plan ambiguous",
                    f"template=artifact_plan_2.png confidence={plan_2.confidence:.3f} threshold=0.820",
                    f"template=artifact_plan_1.png confidence={plan_1.confidence:.3f} threshold=0.640",
                ],
                boxes=[(*self.ARTIFACT_BUTTON_ROI, "go"), (*plan_1.bbox, "label"), (*plan_2.bbox, "status_roi")],
            )
            raise TaskFailedError(
                "Abyss artifact plan ambiguous: "
                f"artifact_plan_2.png={plan_2.confidence:.3f}, artifact_plan_1.png={plan_1.confidence:.3f}"
            )

        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss artifact plan 1",
                f"template=artifact_plan_1.png confidence={plan_1.confidence:.3f}",
                f"template=artifact_plan_2.png confidence={self._match_confidence_text(plan_2)}",
            ],
            boxes=[(*plan_1.bbox, "go")],
        )
        self.context.controller.tap(*plan_1.center)
        time.sleep(TRANSITION_WAIT_SECONDS)
        self._switch_artifact_dialog_to_plan_2()

    def _artifact_plan_2_wins(self, plan_2: Optional[MatchResult], plan_1: Optional[MatchResult]) -> bool:
        if plan_2 is None:
            return False
        if plan_1 is None:
            return True
        return plan_2.confidence >= plan_1.confidence + self.ARTIFACT_PLAN_CONFIDENCE_MARGIN

    def _artifact_plan_1_wins(self, plan_1: MatchResult, plan_2: Optional[MatchResult]) -> bool:
        if plan_2 is None:
            return True
        return plan_1.confidence >= plan_2.confidence + self.ARTIFACT_PLAN_CONFIDENCE_MARGIN

    @staticmethod
    def _match_confidence_text(match: Optional[MatchResult]) -> str:
        return "not_found" if match is None else f"{match.confidence:.3f}"

    def _switch_artifact_dialog_to_plan_2(self) -> None:
        screen = self.context.controller.screenshot()
        tab_2 = self.context.matcher.match_template(
            screen,
            self.asset_path("artifact_tab_2.png"),
            threshold=0.78,
            roi=self.ARTIFACT_TAB_ROI,
        )
        point = tab_2.center if tab_2 else self.ARTIFACT_TAB_2_POINT
        if tab_2 is None:
            self._log("Abyss artifact tab 2 not found; template=artifact_tab_2.png confidence=not_found; using fixed point")
            self._save_abyss_debug(
                "abyss_artifact_tab_2_missing_fallback",
                screen,
                lines=[
                    "Abyss artifact tab 2 not recognized; using fixed point",
                    "template=artifact_tab_2.png confidence=not_found threshold=0.780",
                    f"fixed_point={self.ARTIFACT_TAB_2_POINT[0]},{self.ARTIFACT_TAB_2_POINT[1]}",
                ],
                boxes=[(*self.ARTIFACT_TAB_ROI, "go")],
            )
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss artifact select tab 2",
                (
                    f"template=artifact_tab_2.png confidence={tab_2.confidence:.3f}"
                    if tab_2
                    else "template=artifact_tab_2.png confidence=not_found fallback=fixed_point"
                ),
            ],
            boxes=[(*tab_2.bbox, "go")] if tab_2 else [(595, 95, 60, 40, "go")],
        )
        self.context.controller.tap(*point)
        time.sleep(TRANSITION_WAIT_SECONDS)

        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss artifact unify plan 2",
                "template=none fixed_point=769,397",
            ],
            boxes=[(720, 374, 115, 48, "go")],
        )
        self.context.controller.tap(*self.UNIFY_ARTIFACT_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)

        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss confirm artifact switch",
                "template=none fixed_point=588,402",
            ],
            boxes=[(512, 380, 150, 45, "go")],
        )
        self.context.controller.tap(*self.YES_POINT)
        time.sleep(TRANSITION_WAIT_SECONDS)
        self._tap_confirm_if_visible()

    def _tap_confirm_if_visible(self) -> None:
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("confirm_button.png"),
            threshold=0.58,
            roi=self.CONFIRM_ROI,
        )
        if match is None:
            self._log("Abyss optional confirm not visible; template=confirm_button.png confidence=not_found")
            return
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss confirm",
                f"template=confirm_button.png confidence={match.confidence:.3f}",
            ],
            boxes=[(*match.bbox, "go")],
        )
        self.context.controller.tap(*match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _tap_start_training(self) -> None:
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("start_training_button.png"),
            threshold=0.78,
            roi=(820, 420, 130, 110),
        )
        if match is None:
            self._save_abyss_debug(
                "abyss_start_training_missing",
                screen,
                lines=[
                    "Abyss start training button not recognized",
                    "template=start_training_button.png confidence=not_found threshold=0.780",
                ],
                boxes=[(820, 420, 130, 110, "go")],
            )
            raise TaskFailedError("Abyss start training button not found")
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "abyss start training",
                f"template=start_training_button.png confidence={match.confidence:.3f}",
            ],
            boxes=[(*match.bbox, "go")],
        )
        self.context.controller.tap(*match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _wait_skip_and_keep_result(self) -> None:
        deadline = time.time() + 180
        skip_tapped = False
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            keep_result = self.context.matcher.match_template(
                screen,
                self.asset_path("keep_result_button.png"),
                threshold=0.78,
                roi=self.KEEP_RESULT_ROI,
            )
            if keep_result is not None:
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        "abyss keep result",
                        f"template=keep_result_button.png confidence={keep_result.confidence:.3f}",
                    ],
                    boxes=[(*keep_result.bbox, "go")],
                )
                self.context.controller.tap(*keep_result.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                self._run_post_battle_result_sequence()
                return

            skip = self.context.matcher.match_template(
                screen,
                self.asset_path("skip_button.png"),
                threshold=0.78,
                roi=self.SKIP_ROI,
            )
            if skip is not None:
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        "abyss skip",
                        f"template=skip_button.png confidence={skip.confidence:.3f}",
                    ],
                    boxes=[(*skip.bbox, "go")],
                )
                self.context.controller.tap(*skip.center)
                skip_tapped = True
            self._log("Abyss waiting for battle result" if skip_tapped else "Abyss waiting for skip button")
            time.sleep(1.0)
        raise TaskFailedError("Abyss battle did not reach keep-result screen before timeout")

    def _run_post_battle_result_sequence(self) -> None:
        deadline = time.time() + self.POST_RESULT_TIMEOUT_SECONDS
        taps = 0
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            done = self.context.matcher.match_template(
                screen,
                self.asset_path("final_done_zero.png"),
                threshold=self.FINAL_DONE_STATUS_THRESHOLD,
                roi=self.FINAL_DONE_STATUS_ROI,
            )
            if done is not None:
                self._tap_exit_result_button_with_debug(screen, done)
                return

            for label, asset_name, roi in (
                ("accept result", "accept_result_button.png", self.ACCEPT_RESULT_ROI),
                ("confirm paid challenge", "yes_button.png", self.YES_BUTTON_ROI),
                ("post-keep confirm", "post_keep_confirm_button.png", self.POST_KEEP_CONFIRM_ROI),
            ):
                match = self.context.matcher.match_template(
                    screen,
                    self.asset_path(asset_name),
                    threshold=0.80,
                    roi=roi,
                )
                if match is None:
                    continue
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        f"abyss post-result loop tap {label}",
                        f"{asset_name} confidence={match.confidence:.3f}",
                    ],
                    boxes=[(*match.bbox, "go")],
                )
                self.context.controller.tap(*match.center)
                taps += 1
                time.sleep(self.POST_RESULT_WAIT_SECONDS)
                break
            else:
                self._log("Abyss post-result loop waiting for actionable button")
                time.sleep(1.0)

            if taps > self.POST_RESULT_MAX_TAPS:
                raise TaskFailedError("Abyss post-result loop exceeded tap limit")
        raise TaskFailedError("Abyss post-result loop timed out before final done status")

    def _tap_exit_result_button_with_debug(self, screen, done: MatchResult) -> None:
        current_screen = screen
        current_done: Optional[MatchResult] = done
        last_after = screen
        last_after_done: Optional[MatchResult] = done
        last_after_exit: Optional[MatchResult] = None
        for attempt in range(1, self.EXIT_RESULT_MAX_TAPS + 1):
            exit_match = self.context.matcher.match_template(
                current_screen,
                self.asset_path("exit_button.png"),
                threshold=0.80,
                roi=self.EXIT_BUTTON_ROI,
            )
            boxes = [(*self.FINAL_DONE_STATUS_ROI, "done_status")]
            lines = [
                f"Abyss final done status detected; exit attempt {attempt}/{self.EXIT_RESULT_MAX_TAPS}",
                f"template=final_done_zero.png confidence={self._match_confidence_text(current_done)}",
            ]
            if exit_match is not None:
                boxes.append((*exit_match.bbox, "go"))
                lines.append(f"template=exit_button.png confidence={exit_match.confidence:.3f}")
                point = exit_match.center
            else:
                boxes.append((*self.EXIT_BUTTON_ROI, "go"))
                lines.append("template=exit_button.png confidence=not_found fallback=fixed_roi_center")
                x, y, w, h = self.EXIT_BUTTON_ROI
                point = (x + w // 2, y + h // 2)

            self._save_abyss_debug(
                f"abyss_final_done_before_exit_{attempt:02d}",
                current_screen,
                lines=lines,
                boxes=boxes,
            )
            self.context.controller.annotate_next_tap_debug(
                lines=[
                    f"abyss exit abyss result {attempt}/{self.EXIT_RESULT_MAX_TAPS}",
                    lines[-1],
                ],
                boxes=[boxes[-1]],
            )
            self.context.controller.tap(*point)
            time.sleep(TRANSITION_WAIT_SECONDS)

            after = self.context.controller.screenshot()
            after_done = self.context.matcher.match_template(
                after,
                self.asset_path("final_done_zero.png"),
                threshold=self.FINAL_DONE_STATUS_THRESHOLD,
                roi=self.FINAL_DONE_STATUS_ROI,
            )
            after_exit = self.context.matcher.match_template(
                after,
                self.asset_path("exit_button.png"),
                threshold=0.80,
                roi=self.EXIT_BUTTON_ROI,
            )
            after_boxes = [(*self.FINAL_DONE_STATUS_ROI, "done_status"), (*self.EXIT_BUTTON_ROI, "go")]
            after_lines = [
                f"Abyss after exit tap check {attempt}/{self.EXIT_RESULT_MAX_TAPS}",
                f"template=final_done_zero.png confidence={self._match_confidence_text(after_done)}",
                f"template=exit_button.png confidence={self._match_confidence_text(after_exit)}",
            ]
            self._save_abyss_debug(
                f"abyss_final_done_after_exit_tap_{attempt:02d}",
                after,
                lines=after_lines,
                boxes=after_boxes,
            )
            if after_done is None and after_exit is None:
                self._log(f"Abyss exit result confirmed after tap {attempt}")
                return
            self._log(
                "Abyss exit result still visible after tap "
                f"{attempt}; final_done_zero.png={self._match_confidence_text(after_done)} "
                f"exit_button.png={self._match_confidence_text(after_exit)}"
            )
            current_screen = after
            current_done = after_done
            last_after = after
            last_after_done = after_done
            last_after_exit = after_exit

        self._save_abyss_debug(
            "abyss_final_done_exit_failed",
            last_after,
            lines=[
                "Abyss exit result did not close",
                f"template=final_done_zero.png confidence={self._match_confidence_text(last_after_done)}",
                f"template=exit_button.png confidence={self._match_confidence_text(last_after_exit)}",
            ],
            boxes=[(*self.FINAL_DONE_STATUS_ROI, "done_status"), (*self.EXIT_BUTTON_ROI, "go")],
        )
        raise TaskFailedError(
            "Abyss exit result did not close after repeated taps: "
            f"final_done_zero.png={self._match_confidence_text(last_after_done)}, "
            f"exit_button.png={self._match_confidence_text(last_after_exit)}"
        )

    def _tap_template_step(
        self,
        label: str,
        asset_name: str,
        roi: Roi,
        *,
        timeout_seconds: float,
        threshold: float = 0.80,
    ) -> MatchResult:
        deadline = time.time() + timeout_seconds
        best: Optional[MatchResult] = None
        last_screen = None
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            last_screen = screen
            match = self.context.matcher.match_template(
                screen,
                self.asset_path(asset_name),
                threshold=threshold,
                roi=roi,
            )
            if match is not None:
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        f"abyss {label}",
                        f"{asset_name} confidence={match.confidence:.3f}",
                    ],
                    boxes=[(*match.bbox, "go")],
                )
                self.context.controller.tap(*match.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                return match
            probe = self.context.matcher.best_template_match(screen, self.asset_path(asset_name), roi=roi)
            if probe is not None and (best is None or probe.confidence > best.confidence):
                best = probe
            best_text = "none" if best is None else f"{best.confidence:.3f}"
            self._log(f"Abyss waiting for {label}; template={asset_name} best_confidence={best_text}")
            time.sleep(1.0)
        if last_screen is not None:
            lines = [
                f"Abyss step not found: {label}",
                f"template={asset_name} threshold={threshold:.3f}",
            ]
            if best is not None:
                lines.append(f"best_confidence={best.confidence:.3f}")
            self._save_abyss_debug(
                f"abyss_{asset_name.removesuffix('.png')}_missing",
                last_screen,
                lines=lines,
                boxes=[(*roi, "go")],
            )
        best_suffix = f" best_confidence={best.confidence:.3f}" if best is not None else ""
        raise TaskFailedError(f"Abyss step not found: {label} ({asset_name}){best_suffix}")

    def _best_available_rental(self, rows: list[AbyssRentalRow]) -> Optional[AbyssRentalRow]:
        candidates = [
            row for row in rows
            if row.rent_available
            and row.power_k > 0
            and row.rent_center is not None
            and row.confidence >= self.RENTAL_POWER_MIN_CONFIDENCE
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda row: row.power_k)

    def _power_roi_for_row(self, row_y: int) -> Roi:
        return (self.POWER_ROW_X, row_y + 14, self.POWER_ROW_W, self.POWER_ROW_H)

    def _dragon_roi_for_row(self, row_y: int) -> Roi:
        return (
            self.DRAGON_HERO_ROI_X,
            max(0, row_y - 35),
            self.DRAGON_HERO_ROI_W,
            self.DRAGON_HERO_ROI_H,
        )

    def _rental_row_targets(
        self,
        rent_matches: list[MatchResult],
        rented_matches: list[MatchResult],
    ) -> list[tuple[int, int, MatchResult, str]]:
        targets = []
        row_centers = []
        for match in sorted([*rent_matches, *rented_matches], key=lambda item: item.y):
            if any(abs(match.y - existing) <= self.RENTAL_ROW_TOLERANCE for existing in row_centers):
                continue
            row_centers.append(match.y)

        for row_center in row_centers:
            rent_match = self._nearest_match(rent_matches, row_center)
            rented_match = self._nearest_match(rented_matches, row_center)
            selected = rented_match or rent_match
            if selected is None:
                continue

            if rented_match is not None:
                status = "rented"
            elif rent_match is not None and self._is_active_rent_button(rent_match):
                status = "active"
            else:
                status = "partial"

            row_y = int(selected.y - 26)
            row_index = len(targets) + 1
            targets.append((row_index, row_y, selected, status))
        return targets

    def _nearest_match(self, matches: list[MatchResult], row_center: int) -> Optional[MatchResult]:
        candidates = [match for match in matches if abs(match.y - row_center) <= self.RENTAL_ROW_TOLERANCE]
        if not candidates:
            return None
        return max(candidates, key=lambda match: match.confidence)

    def _is_active_rent_button(self, match: MatchResult) -> bool:
        if match.confidence < self.RENT_BUTTON_ACTIVE_MIN_CONFIDENCE:
            return False
        if match.brightness_ratio is None:
            return True
        return match.brightness_ratio >= self.RENT_BUTTON_ACTIVE_MIN_BRIGHTNESS

    def _rent_match_for_row(self, matches: list[MatchResult], row_y: int) -> Optional[MatchResult]:
        candidates = [match for match in matches if abs(match.y - (row_y + 26)) <= self.RENTAL_ROW_TOLERANCE]
        if not candidates:
            return None
        return min(candidates, key=lambda match: abs(match.y - (row_y + 26)))

    def _save_rental_scan_debug(
        self,
        screen,
        rows: list[AbyssRentalRow],
        rent_matches: list[MatchResult],
        debug_dir: Path,
        scan_index: int,
    ) -> None:
        boxes = []
        for row in rows:
            boxes.append((*self._power_roi_for_row(row.row_y), "label"))
        boxes.extend((*match.bbox, "go") for match in rent_matches)
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is not None:
            path = save_debug(
                f"abyss_rental_scan_{scan_index:02d}",
                screen,
                lines=[
                    f"scan={scan_index}",
                    *[
                        (
                            f"row={row.row_index} power={row.power_text or '?'} "
                            f"k={row.power_k} conf={row.confidence:.2f} "
                            f"rent={self._rent_state(row)} bright={self._format_brightness(row.rent_brightness_ratio)}"
                        )
                        for row in rows
                    ],
                ],
                boxes=boxes,
            )
            if path is not None:
                return

        debug = screen.copy()
        for x, y, w, h, kind in boxes:
            color = (0, 255, 0) if kind == "label" else (255, 0, 0)
            cv2.rectangle(debug, (x, y), (x + w, y + h), color, 2)
        write_image(debug_dir / f"{scan_index:02d}_screen.png", debug)

    def _save_rental_probe_summary(self, rows: list[AbyssRentalRow], debug_dir: Path) -> None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "Abyss rental scan",
            (
                "counts "
                f"active={getattr(self, '_last_rental_scan_active_count', 0)} "
                f"rented={getattr(self, '_last_rental_scan_rented_count', 0)} "
                f"dragon={getattr(self, '_last_rental_scan_dragon_count', 0)}"
            ),
        ]
        for row in rows:
            power = row.power_text or "?"
            file_name = row.crop_path.name
            parent_name = row.crop_path.parent.name
            display_path = str(Path(parent_name) / file_name) if parent_name else file_name
            lines.append(
                f"scan={row.scan_index:02d} row={row.row_index} power=<{power}> "
                f"ocr_conf={row.confidence:.4f} "
                f"rent_conf={row.rent_confidence:.4f} "
                f"rent_bright={self._format_brightness(row.rent_brightness_ratio)} "
                f"file={display_path}"
            )
        (debug_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _rent_state(row: AbyssRentalRow) -> str:
        if row.rent_available:
            return "active"
        if row.rent_brightness_ratio is not None:
            return "dim"
        return "no"

    @staticmethod
    def _format_brightness(value: Optional[float]) -> str:
        return "-" if value is None else f"{value:.3f}"

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            self._ocr_reader = build_easyocr_reader(["en"], download_enabled=False)
        return self._ocr_reader

    def _log(self, message: str) -> None:
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.log(message, force=True)
