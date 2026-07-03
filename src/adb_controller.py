from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.config import (
    ACTION_DEBUG_DIR,
    ACTION_DEBUG_ENABLED,
    ADB_INPUT_TIMEOUT_SECONDS,
    DEFAULT_SERIAL,
    EXPECTED_SCREEN_SIZE,
)
from src.debug_log import DebugLogger
from src.exceptions import BotError, ConfigurationError


class AdbControllerError(BotError):
    """Low-level ADB command failure."""


PREFERRED_FALLBACK_SERIALS: Tuple[str, ...] = ("127.0.0.1:5555", "emulator-5554")

def _sanitize_debug_label(label: Optional[str]) -> str:
    if not label:
        return ""
    cleaned = re.sub(r"[^\w.-]+", "_", str(label).strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._-")
    return cleaned[:80]


class DeviceController:
    """Small ADB wrapper optimized for screenshot-driven UI automation."""

    def __init__(
        self,
        serial: Optional[str] = DEFAULT_SERIAL,
        debug_actions: Optional[bool] = None,
        debug_dir: Optional[Path] = None,
        debug_label: Optional[str] = None,
        logger: Optional[DebugLogger] = None,
    ):
        self.serial = serial or DEFAULT_SERIAL
        self.debug_actions = ACTION_DEBUG_ENABLED if debug_actions is None else debug_actions
        self.logger = logger or DebugLogger(False)
        base_debug_dir = debug_dir or ACTION_DEBUG_DIR
        label = _sanitize_debug_label(debug_label or os.environ.get("VL_ACTION_DEBUG_LABEL"))
        debug_dir_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
        if label:
            debug_dir_name = f"{debug_dir_name}_{label}"
        self.debug_dir = (
            base_debug_dir / debug_dir_name
            if self.debug_actions
            else base_debug_dir
        )
        self._debug_capture_counter = 0
        self._next_tap_debug_lines: List[str] = []
        self._next_tap_debug_boxes: List[Tuple[int, int, int, int, str]] = []

    @property
    def base_cmd(self) -> List[str]:
        return ["adb", "-s", self.serial]

    @staticmethod
    def list_devices() -> List[str]:
        result = subprocess.run(
            ["adb", "devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        if result.returncode != 0:
            raise AdbControllerError(result.stderr.strip())

        devices: List[str] = []
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def connect(self) -> bool:
        if ":" in self.serial:
            result = subprocess.run(
                ["adb", "connect", self.serial],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )
            output = f"{result.stdout}\n{result.stderr}".lower()
            if "connected" in output or "already connected" in output:
                return True
            return self._connect_available_fallback_device()

        if self.serial in PREFERRED_FALLBACK_SERIALS and self._connect_available_fallback_device_once():
            return True
        if self._raw_get_state(self.serial):
            return True
        return self._connect_available_fallback_device()

    @staticmethod
    def _raw_get_state(serial: str) -> bool:
        try:
            result = subprocess.run(
                ["adb", "-s", serial, "get-state"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0 and result.stdout.strip() == "device"

    def _connect_available_fallback_device(self) -> bool:
        if self._connect_available_fallback_device_once():
            return True

        print("[ADB] no usable device after reconnect probe; resetting adb server...")
        if not self._reset_adb_server():
            return False
        return self._connect_available_fallback_device_once()

    def _connect_available_fallback_device_once(self) -> bool:
        for serial in PREFERRED_FALLBACK_SERIALS:
            if ":" not in serial:
                continue
            self._try_adb_connect(serial)

        try:
            devices = self.list_devices()
        except AdbControllerError:
            return False
        if not devices:
            return False

        selected = self._select_fallback_serial(devices)
        if selected is None:
            return False
        if selected != self.serial:
            print(f"[ADB] serial {self.serial!r} unavailable; using {selected!r}")
        self.serial = selected
        return True

    @staticmethod
    def _reset_adb_server() -> bool:
        try:
            subprocess.run(
                ["adb", "kill-server"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )
            time.sleep(1)
            result = subprocess.run(
                ["adb", "start-server"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

    @staticmethod
    def _try_adb_connect(serial: str) -> None:
        subprocess.run(
            ["adb", "connect", serial],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )

    @staticmethod
    def _select_fallback_serial(devices: Sequence[str]) -> Optional[str]:
        for preferred in PREFERRED_FALLBACK_SERIALS:
            if preferred in devices:
                return preferred
        return devices[0] if devices else None

    def get_screen_size(self) -> Tuple[int, int]:
        out = self.shell(["wm", "size"])
        matches = re.findall(r"(\d+)x(\d+)", out)
        if not matches:
            raise AdbControllerError(f"Cannot parse wm size output: {out!r}")
        width, height = matches[-1]
        return int(width), int(height)

    def get_screen_density(self) -> Optional[int]:
        out = self.shell(["wm", "density"])
        match = re.search(r"(\d+)", out)
        return int(match.group(1)) if match else None

    def screenshot(self) -> np.ndarray:
        return self._capture_screen()

    def _capture_screen(self) -> np.ndarray:
        for attempt in range(2):
            cmd = self.base_cmd + ["shell", "screencap", "-p"]
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                raise AdbControllerError(
                    f"ADB screenshot timed out after 30s: {' '.join(cmd)}"
                ) from exc

            if result.returncode == 0:
                break

            stderr = result.stderr.decode("utf-8", errors="ignore").strip()
            if attempt == 0 and self._reconnect_after_adb_error(stderr):
                continue
            raise AdbControllerError(stderr)

        if not result.stdout:
            raise AdbControllerError("screencap returned empty output")

        raw = result.stdout.replace(b"\r\n", b"\n")
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbControllerError("cv2.imdecode failed for ADB screenshot")
        return img

    def save_screenshot(self, path: Path) -> Path:
        image = self._capture_screen()
        self._write_image(path, image)
        return path

    def ensure_screen_size(self, expected: Tuple[int, int] = EXPECTED_SCREEN_SIZE) -> Tuple[int, int]:
        screen = self.screenshot()
        height, width = screen.shape[:2]
        actual = (width, height)
        if actual != expected:
            raise ConfigurationError(
                f"Unsupported screenshot size {actual[0]}x{actual[1]}; "
                f"expected {expected[0]}x{expected[1]}."
            )
        return actual

    def tap(self, x: int, y: int) -> None:
        ix, iy = int(x), int(y)
        self._run_input_with_debug(
            f"tap_{ix}_{iy}",
            ["shell", "input", "tap", str(ix), str(iy)],
        )

    def annotate_next_tap_debug(
        self,
        *,
        lines: Sequence[str] = (),
        boxes: Sequence[Tuple[int, int, int, int, str]] = (),
    ) -> None:
        self._next_tap_debug_lines = list(lines)
        self._next_tap_debug_boxes = list(boxes)

    def save_annotated_debug(
        self,
        label: str,
        image: np.ndarray,
        *,
        lines: Sequence[str] = (),
        boxes: Sequence[Tuple[int, int, int, int, str]] = (),
        panel_position: str = "left",
    ) -> Optional[Path]:
        if not self.debug_actions:
            return None
        annotated = self._annotate_action_debug_image(
            image,
            debug_lines=lines,
            debug_boxes=boxes,
            debug_panel_position=panel_position,
        )
        return self._save_debug_image(label, annotated)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self.swipe(x, y, x, y, duration_ms=duration_ms)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        ix1, iy1, ix2, iy2, iduration = int(x1), int(y1), int(x2), int(y2), int(duration_ms)
        self._run_input_with_debug(
            f"swipe_{ix1}_{iy1}_{ix2}_{iy2}_{iduration}",
            [
                "shell",
                "input",
                "swipe",
                str(ix1),
                str(iy1),
                str(ix2),
                str(iy2),
                str(iduration),
            ],
        )

    def back(self) -> None:
        self.keyevent(4)

    def keyevent(self, keycode: int) -> None:
        ikeycode = int(keycode)
        self._run_input_with_debug(
            f"keyevent_{ikeycode}",
            ["shell", "input", "keyevent", str(ikeycode)],
        )

    def shell(self, args: Sequence[str]) -> str:
        result = self._run(["shell"] + list(args), timeout=10)
        return result.stdout

    def _run_input_with_debug(
        self,
        action_name: str,
        args: Iterable[str],
        timeout: int = ADB_INPUT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess:
        if not self.debug_actions:
            return self._run(args, timeout=timeout)

        tap_point = self._tap_point_from_action_name(action_name)
        swipe_points = self._swipe_points_from_action_name(action_name)
        debug_lines = self._consume_next_tap_debug_lines()
        debug_boxes = self._consume_next_tap_debug_boxes()
        debug_lines = self._action_debug_lines(action_name) + debug_lines
        self._save_action_debug_screenshot(
            f"before_{action_name}",
            tap_point=tap_point,
            swipe_points=swipe_points,
            debug_lines=debug_lines,
            debug_boxes=debug_boxes,
        )
        result = self._run(args, timeout=timeout)
        time.sleep(0.6)
        self._save_action_debug_screenshot(
            f"after_{action_name}",
            tap_point=tap_point,
            swipe_points=swipe_points,
            debug_lines=debug_lines,
            debug_boxes=debug_boxes,
        )
        return result

    def _save_action_debug_screenshot(
        self,
        label: str,
        *,
        tap_point: Optional[Tuple[int, int]] = None,
        swipe_points: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None,
        debug_lines: Sequence[str] = (),
        debug_boxes: Sequence[Tuple[int, int, int, int, str]] = (),
    ) -> Path:
        image = self._capture_screen()
        if tap_point is not None or swipe_points is not None or debug_lines or debug_boxes:
            image = self._annotate_action_debug_image(
                image,
                tap_point=tap_point,
                swipe_points=swipe_points,
                debug_lines=debug_lines,
                debug_boxes=debug_boxes,
            )
        return self._save_debug_image(label, image)

    def _save_debug_image(self, label: str, image: np.ndarray) -> Path:
        self._debug_capture_counter += 1
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
        path = self.debug_dir / f"{self._debug_capture_counter:06d}_{timestamp}_{safe_label}.png"
        self._write_image(path, image)
        return path

    @staticmethod
    def _write_image(path: Path, image: np.ndarray) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", image)
        if not ok:
            raise AdbControllerError("cv2.imencode failed for screenshot")
        path.write_bytes(buf.tobytes())

    def _consume_next_tap_debug_lines(self) -> List[str]:
        lines = self._next_tap_debug_lines
        self._next_tap_debug_lines = []
        return lines

    def _consume_next_tap_debug_boxes(self) -> List[Tuple[int, int, int, int, str]]:
        boxes = self._next_tap_debug_boxes
        self._next_tap_debug_boxes = []
        return boxes

    @staticmethod
    def _tap_point_from_action_name(action_name: str) -> Optional[Tuple[int, int]]:
        match = re.fullmatch(r"tap_(\d+)_(\d+)", action_name)
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _swipe_points_from_action_name(action_name: str) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
        match = re.fullmatch(r"swipe_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)", action_name)
        if match is None:
            return None
        x1, y1, x2, y2, _duration = (int(value) for value in match.groups())
        return (x1, y1), (x2, y2)

    @staticmethod
    def _action_debug_lines(action_name: str) -> List[str]:
        if action_name.startswith("keyevent_"):
            keycode = action_name.removeprefix("keyevent_")
            label = "BACK" if keycode == "4" else keycode
            return [f"action=keyevent {label}"]
        if action_name.startswith("swipe_"):
            return [f"action={action_name}"]
        if action_name.startswith("tap_"):
            return [f"action={action_name}"]
        return [f"action={action_name}"]

    @staticmethod
    def _annotate_action_debug_image(
        image: np.ndarray,
        *,
        tap_point: Optional[Tuple[int, int]] = None,
        swipe_points: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None,
        debug_lines: Sequence[str] = (),
        debug_boxes: Sequence[Tuple[int, int, int, int, str]] = (),
        debug_panel_position: str = "left",
    ) -> np.ndarray:
        annotated = image.copy()
        palette = {
            "label": (0, 255, 0),
            "label_roi": (255, 0, 255),
            "go": (0, 0, 255),
            "done_status": (0, 215, 255),
            "tap": (0, 0, 255),
            "roi": (255, 255, 0),
            "status_roi": (0, 165, 255),
        }
        for x, y, width, height, kind in debug_boxes:
            color = palette.get(kind, (255, 255, 255))
            cv2.rectangle(annotated, (x, y), (x + width, y + height), color, 2)
            if kind:
                cv2.putText(
                    annotated,
                    kind,
                    (x, max(14, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    color,
                    1,
                    cv2.LINE_AA,
                )

        if tap_point is not None:
            x, y = tap_point
            cv2.drawMarker(
                annotated,
                (x, y),
                palette["tap"],
                markerType=cv2.MARKER_CROSS,
                markerSize=34,
                thickness=3,
            )
            cv2.circle(annotated, (x, y), 18, palette["tap"], 2)
            cv2.putText(
                annotated,
                f"tap {x},{y}",
                (min(x + 22, annotated.shape[1] - 130), max(22, y - 22)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                palette["tap"],
                2,
                cv2.LINE_AA,
            )

        if swipe_points is not None:
            start, end = swipe_points
            cv2.arrowedLine(annotated, start, end, palette["tap"], 3, cv2.LINE_AA, tipLength=0.18)
            for label, point in (("swipe start", start), ("swipe end", end)):
                x, y = point
                cv2.circle(annotated, (x, y), 12, palette["tap"], 2)
                cv2.putText(
                    annotated,
                    f"{label} {x},{y}",
                    (min(x + 16, annotated.shape[1] - 180), max(22, y - 16)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.50,
                    palette["tap"],
                    2,
                    cv2.LINE_AA,
                )

        lines = list(debug_lines)
        if tap_point is not None and not any(line.startswith("tap ") for line in lines):
            lines.insert(0, f"tap {tap_point[0]},{tap_point[1]}")
        if swipe_points is not None and not any(line.startswith("swipe ") for line in lines):
            start, end = swipe_points
            lines.insert(0, f"swipe {start[0]},{start[1]} -> {end[0]},{end[1]}")
        if lines:
            line_height = 20
            text_scale = 0.48
            text_thickness = 1
            padding_x = 8
            padding_top = 8
            padding_bottom = 7
            margin = 8
            truncated_lines = [line[:92] for line in lines]
            max_text_width = max(
                cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, text_scale, text_thickness)[0][0]
                for line in truncated_lines
            )
            panel_height = padding_top + padding_bottom + line_height * len(truncated_lines)
            panel_width = max_text_width + padding_x * 2
            if debug_panel_position == "right":
                panel_x1 = max(margin, annotated.shape[1] - panel_width - margin)
            else:
                panel_x1 = margin
            panel_x2 = min(annotated.shape[1] - margin, panel_x1 + panel_width)
            panel_y2 = annotated.shape[0] - margin
            panel_y1 = max(margin, panel_y2 - panel_height)
            text_x = panel_x1 + padding_x
            cv2.rectangle(annotated, (panel_x1, panel_y1), (panel_x2, panel_y2), (0, 0, 0), -1)
            cv2.rectangle(annotated, (panel_x1, panel_y1), (panel_x2, panel_y2), (255, 255, 255), 1)
            for index, line in enumerate(truncated_lines):
                cv2.putText(
                    annotated,
                    line,
                    (text_x, panel_y1 + padding_top + 13 + index * line_height),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    text_scale,
                    (255, 255, 255),
                    text_thickness,
                    cv2.LINE_AA,
                )
        return annotated

    def _run(
        self,
        args: Iterable[str],
        timeout: int = 15,
    ) -> subprocess.CompletedProcess:
        adb_args = list(args)
        for attempt in range(2):
            cmd = self.base_cmd + adb_args
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise AdbControllerError(
                    f"ADB command timed out after {timeout}s: {' '.join(cmd)}"
                ) from exc
            if result.returncode == 0:
                return result
            if attempt == 0 and self._reconnect_after_adb_error(result.stderr):
                continue
            raise AdbControllerError(
                f"ADB command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
            )
        raise AdbControllerError("ADB command failed after reconnect retry")

    @staticmethod
    def _is_reconnectable_adb_error(message: str) -> bool:
        normalized = str(message).lower()
        if "device" in normalized and "not found" in normalized:
            return True
        return any(marker in normalized for marker in ("offline", "no devices/emulators found"))

    def _reconnect_after_adb_error(self, message: str) -> bool:
        if not self._is_reconnectable_adb_error(message):
            return False
        old_serial = self.serial
        print(f"[ADB] connection lost for {old_serial!r}: {str(message).strip()}; reconnecting...")
        if not self.connect():
            return False
        if self.serial != old_serial:
            print(f"[ADB] reconnected using {self.serial!r}")
        return True
