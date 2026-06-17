"""
image_io.py — 圖片讀寫與標註工具

從 src/vision_matcher.py 的 read_image / write_image 提取，
並新增 annotate_image（畫框 + 印文字）。

─────────────────────────────────────────────────────
介面
─────────────────────────────────────────────────────

def read_image(path: Path) -> np.ndarray:
    \"\"\"讀取圖片，失敗時 raise IOError。\"\"\"

def write_image(path: Path, image: np.ndarray) -> Path:
    \"\"\"儲存圖片，自動建立父目錄，回傳儲存路徑。\"\"\"

def annotate_image(
    image: np.ndarray,
    *,
    rois: Optional[List[Tuple[int, int, int, int]]] = None,  # (x, y, w, h)
    roi_color: Tuple[int, int, int] = (0, 0, 255),           # BGR 紅色
    texts: Optional[List[str]] = None,                        # 印在左上角
    font_scale: float = 0.6,
) -> np.ndarray:
    \"\"\"
    在圖片上標註 ROI 矩形框和文字說明（不修改原圖，回傳新 array）。
    供 DebugCapture.save_failure() 使用。
    \"\"\"
"""

# TODO: 實作 read_image, write_image, annotate_image
