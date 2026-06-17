"""
crop_tool.py — 藍框偵測與 ROI 裁切工具

從 src/paint_cropper.py 提取核心功能，供 src_v2 和 ads2 共用。

─────────────────────────────────────────────────────
介面
─────────────────────────────────────────────────────

@dataclass(frozen=True)
class CropBox:
    x: int; y: int; width: int; height: int

def find_blue_boxes(image: np.ndarray) -> List[CropBox]:
    \"\"\"偵測截圖中 Paint 風格的藍色矩形框，回傳所有找到的 CropBox。\"\"\"

def crop_roi(image: np.ndarray, box: CropBox) -> np.ndarray:
    \"\"\"從圖片裁切指定的 CropBox 區域。\"\"\"

def save_crops(
    image: np.ndarray,
    boxes: List[CropBox],
    output_dir: Path,
    prefix: str = "crop",
) -> List[Path]:
    \"\"\"將所有 CropBox 裁切並儲存，回傳儲存路徑列表。\"\"\"
"""

# TODO: 從 src/paint_cropper.py 遷移 find_blue_boxes 等邏輯
