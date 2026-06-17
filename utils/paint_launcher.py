"""
paint_launcher.py — 開小畫家工具

從 src/paint_cropper.py 提取，供 src_v2 和 ads2 共用。

─────────────────────────────────────────────────────
介面
─────────────────────────────────────────────────────

def open_in_paint(image_path: Path) -> None:
    \"\"\"用 Windows 小畫家開啟指定圖片。\"\"\"

def open_and_wait(image_path: Path, timeout_seconds: float = 120.0) -> bool:
    \"\"\"
    開啟小畫家並等待使用者關閉。
    回傳 True 表示正常關閉，False 表示 timeout。
    \"\"\"
"""

# TODO: 從 src/paint_cropper.py 遷移 paint 啟動邏輯
