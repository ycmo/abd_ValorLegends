"""
debug_capture.py — 集中管理所有 debug 截圖

Phase 1 輕量版：
  - save_failure()：儲存截圖，檔名帶 roi / best_conf / threshold 資訊，不做 cv2 框繪製
  - save_action()：before/after 截圖，session 目錄結構完整
  - cleanup()：刪最舊 sessions，保留最新 N 個
  - cv2 ROI annotation：Phase 2 補

Session 目錄結構：
  captures/
    sessions/
      20260615_084500_pid1234/
        guild_wish/
          step_01_free_button/
            before.png
            after.png
          fail_free_wish_button__roi_165_360_220_95__conf_0.61__thr_0.86.png
      latest -> 20260615_084500_pid1234/   (junction on Windows)
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

import numpy as np

from src.vision_matcher import Roi, write_image


class DebugCapture:
    """集中管理 debug 截圖的 session 物件。"""

    def __init__(self, session_dir: Path, enabled: bool = True) -> None:
        self.session_dir = session_dir
        self.enabled = enabled
        self._step_counters: dict[str, int] = {}
        self.last_failure_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def save_failure(
        self,
        screen: np.ndarray,
        task_key: str,
        step_label: str,
        roi: Optional[Roi],
        best_confidence: Optional[float],
        threshold: float,
    ) -> Optional[Path]:
        """
        儲存失敗截圖。

        檔名格式：
          fail_{step_label}__{roi_str}__{conf_str}__thr_{threshold:.2f}.png

        回傳儲存路徑（供 TaskFailedError message 使用）。
        Phase 1：不做 cv2 ROI 框繪製，只儲存原始截圖。
        """
        if not self.enabled:
            self.last_failure_path = None
            return None

        roi_str = f"roi_{roi[0]}_{roi[1]}_{roi[2]}_{roi[3]}" if roi else "roi_full"
        conf_str = f"conf_{best_confidence:.2f}" if best_confidence is not None else "conf_none"
        filename = (
            f"fail_{_safe_label(step_label)}__{roi_str}__{conf_str}"
            f"__thr_{threshold:.2f}.png"
        )
        dest = self.session_dir / task_key / filename
        self.last_failure_path = dest
        return write_image(dest, screen)

    def save_action(
        self,
        screen: np.ndarray,
        task_key: str,
        step_label: str,
        phase: Literal["before", "after"],
    ) -> Path:
        """
        --debug-actions 模式專用。

        每個 step_label 建立獨立子目錄，按呼叫順序編號：
          guild_wish/step_01_free_button/before.png
          guild_wish/step_01_free_button/after.png
        """
        if not self.enabled:
            return Path("")

        counter_key = f"{task_key}:{step_label}"
        if phase == "before":
            idx = self._step_counters.get(counter_key, 0) + 1
            self._step_counters[counter_key] = idx
        else:
            idx = self._step_counters.get(counter_key, 1)

        step_dir = self.session_dir / task_key / f"step_{idx:02d}_{_safe_label(step_label)}"
        dest = step_dir / f"{phase}.png"
        return write_image(dest, screen)

    @staticmethod
    def cleanup(captures_dir: Path, keep_sessions: int = 5) -> int:
        """
        刪除 captures/sessions/ 下最舊的 session，保留最新 keep_sessions 個。
        回傳實際刪除的 session 數量。
        """
        sessions_dir = captures_dir / "sessions"
        if not sessions_dir.exists():
            return 0

        # 只列出真實目錄（排除 symlink/junction 的 latest）
        session_dirs = sorted(
            [
                d
                for d in sessions_dir.iterdir()
                if d.is_dir() and d.name != "latest"
            ],
            key=lambda d: d.stat().st_mtime,
        )
        to_delete = session_dirs[: max(0, len(session_dirs) - keep_sessions)]
        for d in to_delete:
            shutil.rmtree(d, ignore_errors=True)
        return len(to_delete)

    # ------------------------------------------------------------------
    # factory
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, captures_dir: Path, enabled: bool = True) -> "DebugCapture":
        """
        建立一個新 session 目錄，並更新 captures/sessions/latest junction。
        session 目錄名：YYYYMMDD_HHMMSS_pid{PID}
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        pid = os.getpid()
        session_name = f"{timestamp}_pid{pid}"
        sessions_dir = captures_dir / "sessions"
        session_dir = sessions_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)

        # 更新 latest junction（Windows 使用 junction；非 Windows 使用 symlink）
        _update_latest_link(sessions_dir, session_dir)

        return cls(session_dir=session_dir, enabled=enabled)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _safe_label(label: str) -> str:
    """將 step label 轉為適合放在檔名裡的字串。"""
    return label.strip().lower().replace(" ", "_").replace("/", "_").replace("\\", "_")


def _update_latest_link(sessions_dir: Path, target: Path) -> None:
    """在 sessions_dir/latest 建立指向 target 的 junction（Windows）或 symlink（其他）。"""
    latest = sessions_dir / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            if latest.is_dir() and not latest.is_symlink():
                # Windows junction 用 rmdir 刪
                latest.rmdir()
            else:
                latest.unlink()
    except OSError:
        return  # 建立失敗不影響主流程

    try:
        if os.name == "nt":
            # Windows junction
            import subprocess
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(latest), str(target)],
                check=True,
                capture_output=True,
            )
        else:
            latest.symlink_to(target, target_is_directory=True)
    except Exception:
        pass  # latest 建立失敗不影響主功能
