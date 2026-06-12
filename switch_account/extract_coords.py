import cv2
import numpy as np
from pathlib import Path

src_dir = Path(r"E:\antigravity\adb_vl\manual_screenshots\帳號切換")

with open("output.txt", "w", encoding="utf-8") as f:
    for img_path in sorted(src_dir.glob("*.png")):
        # img = cv2.imread(str(img_path))
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None: continue
        
        lower_red = np.array([0, 0, 200])
        upper_red = np.array([60, 60, 255])
        mask = cv2.inRange(img, lower_red, upper_red)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        boxes = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w > 10 and h > 10:
                cx, cy = x + w//2, y + h//2
                boxes.append((y, cx, cy, x, y, w, h))
                
        boxes.sort()
        
        f.write(f"--- {img_path.name} ---\n")
        for b in boxes:
            _, cx, cy, x, y, w, h = b
            f.write(f"Center: ({cx}, {cy}), Box: x={x}, y={y}, w={w}, h={h}\n")

