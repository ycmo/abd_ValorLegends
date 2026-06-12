import cv2
import numpy as np
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
src_dir = PROJECT_ROOT / "manual_screenshots" / "串接"
tpl_dir = PROJECT_ROOT / "AwayFromKeyboard" / "integration_task" / "templates"

pairs = [
    ("000_掛機寶箱任務.png", "000_掛機寶箱任務_target_1.png"),
    ("000_關閉寶箱.png", "000_關閉寶箱_target_0.png"),
    ("001_任務返回.png", "001_任務返回_target_3.png"),
    ("002_進入王國事件.png", "002_進入王國事件_target_0.png"),
    ("002_進入異界奇聞2.png", "002_進入異界奇聞2_target_8.png"),
    ("003_進入異界奇聞.png", "003_進入異界奇聞_target_0.png"),
    ("005_返回.png", "005_返回_target_13.png")
]

rois = {}

for img_name, tpl_name in pairs:
    img_path = src_dir / img_name
    tpl_path = tpl_dir / tpl_name
    
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    tpl = cv2.imdecode(np.fromfile(tpl_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    
    if img is None or tpl is None:
        print(f"Failed to load {img_name} or {tpl_name}")
        continue
        
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    
    h, w = tpl.shape[:2]
    x, y = max_loc
    
    # Calculate ROI: [x-50, y-50, w+100, h+100]
    rx = max(0, x - 50)
    ry = max(0, y - 50)
    rw = min(img.shape[1] - rx, w + 100)
    rh = min(img.shape[0] - ry, h + 100)
    
    if "003" in img_name:
        # special case for 003: relax Y to full height, lock X
        ry = 0
        rh = img.shape[0]
        
    rois[img_name[:3]] = {
        "x": x, "y": y, "w": w, "h": h,
        "roi": [int(rx), int(ry), int(rw), int(rh)]
    }
    print(f"Matched {img_name[:3]}: at ({x}, {y}) size ({w}x{h}). ROI: {[int(rx), int(ry), int(rw), int(rh)]}")

with open(tpl_dir / "rois.json", "w") as f:
    json.dump(rois, f, indent=4)
