"""
adb_controller.py
-----------------
DeviceController: 封裝 ADB 操作，支援 serial 指定、記憶體擷圖、tap、back、設備資訊查詢。

擷圖策略（Windows 優化）：
  使用 subprocess.PIPE 直接讀取 `adb shell screencap -p` 的標準輸出二進位流，
  移除 Windows ADB 傳輸造成的 CR/LF 換行污染，再以 cv2.imdecode() 在記憶體中解碼。
  避免透過 /sdcard 中轉，每次擷圖可節省 1~1.5 秒。
"""

import subprocess
import sys
import numpy as np
import cv2
from typing import Optional, Tuple


class AdbControllerError(Exception):
    pass


class DeviceController:
    def __init__(self, serial: Optional[str] = None):
        """
        Parameters
        ----------
        serial : str, optional
            ADB device serial，例如 "127.0.0.1:5555"（模擬器）或 "emulator-5554"。
            若為 None，則預設讀取 status_graph.json 的 device_config。
        """
        if serial is None:
            from adb_client import ADB_TARGET
            serial = ADB_TARGET
        self.serial = serial
        self._base_cmd = ["adb", "-s", serial]

    # ------------------------------------------------------------------
    # 連線
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        嘗試連線到設備（TCP/IP 模擬器）。
        回傳 True 表示連線成功或已連線，False 表示失敗。
        """
        try:
            result = subprocess.run(
                ["adb", "connect", self.serial],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )
            output = result.stdout.strip()
            print(f"[ADB] connect → {output}")
            # "already connected" or "connected to" → 成功
            return "connected" in output.lower()
        except Exception as e:
            print(f"[ADB] connect failed: {e}", file=sys.stderr)
            return False

    # ------------------------------------------------------------------
    # 設備資訊
    # ------------------------------------------------------------------

    def get_screen_size(self) -> Tuple[int, int]:
        """
        呼叫 `adb shell wm size`，回傳 (width, height)。
        """
        out = self._shell("wm size")
        # 回傳格式: "Physical size: 1600x900" 或 "Override size: 1600x900"
        for line in out.splitlines():
            if "size:" in line.lower():
                parts = line.strip().split(":")[-1].strip()
                w, h = parts.split("x")
                return int(w), int(h)
        raise AdbControllerError(f"Cannot parse wm size output: {out!r}")

    def get_screen_density(self) -> int:
        """
        呼叫 `adb shell wm density`，回傳 DPI。
        """
        out = self._shell("wm density")
        for line in out.splitlines():
            if "density:" in line.lower():
                return int(line.strip().split(":")[-1].strip())
        raise AdbControllerError(f"Cannot parse wm density output: {out!r}")

    # ------------------------------------------------------------------
    # 擷圖
    # ------------------------------------------------------------------

    def screenshot(self) -> np.ndarray:
        """
        透過 ADB PIPE 擷圖，在記憶體中解碼，回傳 BGR numpy array (OpenCV 格式)。

        Windows 處理說明：
          Windows ADB 在傳輸文字模式管道時會將 \\n → \\r\\n，
          導致 PNG 標頭的 \\n (0x0A) 被替換為 \\r\\n (0x0D 0x0A)，破壞圖片格式。
          修正：先將 bytes 中的 0x0D 0x0A 替換回 0x0A。
        """
        cmd = self._base_cmd + ["shell", "screencap", "-p"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            raw, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AdbControllerError("screencap timeout exceeded")
        except Exception as e:
            raise AdbControllerError(f"screencap subprocess error: {e}")

        if proc.returncode != 0:
            raise AdbControllerError(
                f"screencap returned non-zero: {proc.returncode}, stderr={err!r}"
            )

        if not raw:
            raise AdbControllerError("screencap returned empty output")

        # Windows 換行修正：\r\n → \n（二進位替換）
        raw_fixed = raw.replace(b"\r\n", b"\n")

        img_array = np.frombuffer(raw_fixed, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None:
            raise AdbControllerError(
                "cv2.imdecode failed: PNG data corrupted. "
                "Check if Windows CRLF replacement is correct."
            )

        return img

    # ------------------------------------------------------------------
    # 輸入控制
    # ------------------------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        """發送 tap 到 (x, y)。"""
        self._run(["shell", "input", "tap", str(x), str(y)])

    def back(self) -> None:
        """發送 Android Back 鍵（keyevent 4）。"""
        self._run(["shell", "input", "keyevent", "4"])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """發送 swipe 指令。"""
        self._run(["shell", "input", "swipe",
                   str(x1), str(y1), str(x2), str(y2), str(duration_ms)])

    # ------------------------------------------------------------------
    # 內部工具
    # ------------------------------------------------------------------

    def _shell(self, cmd_str: str) -> str:
        """執行 `adb -s <serial> shell <cmd_str>`，回傳 stdout 文字。"""
        result = subprocess.run(
            self._base_cmd + ["shell"] + cmd_str.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        return result.stdout

    def _run(self, args: list) -> subprocess.CompletedProcess:
        """執行帶有 serial 的 ADB 指令，失敗時拋出 AdbControllerError。"""
        cmd = self._base_cmd + args
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
        )
        if result.returncode != 0:
            raise AdbControllerError(
                f"ADB command failed: {' '.join(cmd)}\n"
                f"stderr: {result.stderr.strip()}"
            )
        return result
