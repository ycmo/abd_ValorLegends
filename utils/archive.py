"""
archive.py — 截圖歸檔與 session 清理工具

─────────────────────────────────────────────────────
Session 目錄結構
─────────────────────────────────────────────────────
captures/
  sessions/
    20260615_084500_pid1234/   ← session_dir
    20260614_220000_pid5678/
  latest/                      ← Windows junction 指向最新 session

─────────────────────────────────────────────────────
介面
─────────────────────────────────────────────────────

def new_session(captures_dir: Path) -> Path:
    \"\"\"
    建立新的 session 目錄（以當前時間 + pid 命名），
    更新 captures/latest junction 指向此目錄，
    回傳 session_dir Path。
    \"\"\"

def cleanup_sessions(captures_dir: Path, keep: int = 5) -> int:
    \"\"\"
    掃描 captures/sessions/，依建立時間排序，
    刪除最舊的 session 直到只剩 keep 個。
    回傳刪除的 session 數量。
    \"\"\"

def session_count(captures_dir: Path) -> int:
    \"\"\"回傳目前 session 數量。\"\"\"
"""

# TODO: 實作 archive 功能
