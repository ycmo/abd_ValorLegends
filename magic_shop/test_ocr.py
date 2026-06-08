import sys
import os
from pathlib import Path
import cv2

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ocr_utils import build_easyocr_reader

def main():
    reader = build_easyocr_reader()
    assets_dir = Path(r"E:\antigravity\adb_vl\magic_shop\assets")
    debug_dir = Path(r"E:\antigravity\adb_vl\magic_shop\debug_output")

    print("=== Testing Assets ===")
    for img_path in assets_dir.glob("*.png"):
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        # Test directly
        res = reader.readtext(img, detail=1, allowlist="0123456789km,", mag_ratio=2.0)
        fragments = [(text, conf) for _, text, conf in res]
        print(f"{img_path.name}: {fragments}")

    print("\n=== Testing Debug Output ===")
    # Just test the first few to avoid spam
    for img_path in list(debug_dir.glob("*.png"))[:3]:
        img = cv2.imread(str(img_path))
        if img is None:
            continue

        # Apply the ROI logic used in the task
        ocr_roi = (250, 100, 710, 440)
        x, y, w, h = ocr_roi
        roi_img = img[y:y+h, x:x+w]

        res = reader.readtext(roi_img, detail=1, allowlist="0123456789km,", mag_ratio=2.0)
        fragments = [(text, conf) for _, text, conf in res if conf > 0.5]
        print(f"{img_path.name} (filtered conf > 0.5):")
        for f in fragments:
            print(f"  {f}")

if __name__ == "__main__":
    main()
