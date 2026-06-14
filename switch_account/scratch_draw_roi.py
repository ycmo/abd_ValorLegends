import cv2
import numpy as np
from pathlib import Path
import os

img_path = Path(r"E:\antigravity\adb_vl\manual_screenshots\帳號切換\008_伺服器列表.png")
artifact_dir = Path(r"C:\Users\USER\.gemini\antigravity-cli\brain\67ef3329-f092-438f-bd7e-a5f971db20cb")
target_path = artifact_dir / "roi_preview.png"

img_array = np.fromfile(str(img_path), np.uint8)
img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
if img is None:
    print("Failed to load image")
    exit(1)

# Draw ROI box
roi = (329, 36, 627, 162)
x, y, w, h = roi

cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 3)
cv2.putText(img, "Current ROI (329, 36, w:627, h:162)", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

ok, buf = cv2.imencode(".png", img)
if ok:
    target_path.write_bytes(buf.tobytes())
    print(f"Saved to {target_path}")
else:
    print("Failed to encode image")
