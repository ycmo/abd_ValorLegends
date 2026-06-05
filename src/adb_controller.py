from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.config import DEFAULT_SERIAL, EXPECTED_SCREEN_SIZE
from src.exceptions import ConfigurationError


class AdbControllerError(Exception):
    """Low-level ADB command failure."""


class DeviceController:
    """Small ADB wrapper optimized for screenshot-driven UI automation."""

    def __init__(self, serial: str = DEFAULT_SERIAL):
        self.serial = serial

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
        image = self.screenshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", image)
        if not ok:
            raise AdbControllerError("cv2.imencode failed for screenshot")
        path.write_bytes(buf.tobytes())
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
        self._run(["shell", "input", "tap", str(int(x)), str(int(y))])

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self.swipe(x, y, x, y, duration_ms=duration_ms)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._run(
            [
                "shell",
                "input",
                "swipe",
                str(int(x1)),
                str(int(y1)),
                str(int(x2)),
                str(int(y2)),
                str(int(duration_ms)),
            ]
        )

    def back(self) -> None:
        self.keyevent(4)

    def keyevent(self, keycode: int) -> None:
        self._run(["shell", "input", "keyevent", str(int(keycode))])

    def shell(self, args: Sequence[str]) -> str:
        result = self._run(["shell"] + list(args), timeout=10)
        return result.stdout

    def _run(
        self,
        args: Iterable[str],
        timeout: int = 15,
    ) -> subprocess.CompletedProcess:
        cmd = self.base_cmd + list(args)
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
        )
        if result.returncode != 0:
            raise AdbControllerError(
                f"ADB command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
            )
        return result

