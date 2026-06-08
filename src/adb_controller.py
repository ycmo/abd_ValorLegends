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
from src.exceptions import ConfigurationError


class AdbControllerError(Exception):
    """Low-level ADB command failure."""


class DeviceController:
    """Small ADB wrapper optimized for screenshot-driven UI automation."""

    def __init__(
        self,
        serial: str = DEFAULT_SERIAL,
        debug_actions: Optional[bool] = None,
        debug_dir: Optional[Path] = None,
    ):
        self.serial = serial
        self.debug_actions = ACTION_DEBUG_ENABLED if debug_actions is None else debug_actions
        base_debug_dir = debug_dir or ACTION_DEBUG_DIR
        self.debug_dir = (
            base_debug_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
            if self.debug_actions
            else base_debug_dir
        )
        self._debug_capture_counter = 0

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
            return "connected" in output or "already connected" in output

        try:
            self._run(["get-state"], timeout=10)
            return True
        except AdbControllerError:
            return False

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
        img = self._capture_screen()
        if self.debug_actions:
            self._save_debug_image("screen", img)
        return img

    def _capture_screen(self) -> np.ndarray:
        result = subprocess.run(
            self.base_cmd + ["shell", "screencap", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if result.returncode != 0:
            raise AdbControllerError(result.stderr.decode("utf-8", errors="ignore").strip())
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

        self._save_action_debug_screenshot(f"before_{action_name}")
        result = self._run(args, timeout=timeout)
        time.sleep(0.6)
        self._save_action_debug_screenshot(f"after_{action_name}")
        return result

    def _save_action_debug_screenshot(self, label: str) -> Path:
        image = self._capture_screen()
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

    def _run(
        self,
        args: Iterable[str],
        timeout: int = 15,
    ) -> subprocess.CompletedProcess:
        cmd = self.base_cmd + list(args)
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
        if result.returncode != 0:
            raise AdbControllerError(
                f"ADB command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
            )
        return result
