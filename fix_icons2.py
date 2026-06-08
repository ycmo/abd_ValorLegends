import cv2
import numpy as np
from pathlib import Path

base_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\1_templates\close_icons")

# 2. 修正截歪的 close_skip_1 和 close_skip_2 (去除紅色殘留邊界)
for f in ["close_skip_1.png", "close_skip_2.png"]:
    p = base_dir / f
    if not p.exists(): continue
    img = cv2.imread(str(p))
    
    # 找出紅色像素
    lower_red = np.array([0, 0, 200])
    upper_red = np.array([80, 80, 255])
    mask = cv2.inRange(img, lower_red, upper_red)
    
    h, w = img.shape[:2]
    
    col_sums = np.sum(mask > 0, axis=0)
    row_sums = np.sum(mask > 0, axis=1)
    
    left = 0
    while left < w and col_sums[left] > h * 0.1: left += 1
    
    right = w
    while right > left and col_sums[right-1] > h * 0.1: right -= 1
        
    top = 0
    while top < h and row_sums[top] > w * 0.1: top += 1
        
    bottom = h
    while bottom > top and row_sums[bottom-1] > w * 0.1: bottom -= 1
        
    # 再往內縮 1 pixel 確保乾淨
    if top < h: top += 1
    if bottom > 0: bottom -= 1
    if left < w: left += 1
    if right > 0: right -= 1
    
    if left < right and top < bottom:
        cropped = img[top:bottom, left:right]
        cv2.imwrite(str(p), cropped)
        print(f"Fixed {f} (New size: {cropped.shape[1]}x{cropped.shape[0]})")

# 3. 縮小 ad_issue_20260606_081550_roi_9.png
p9 = base_dir / "ad_issue_20260606_081550_roi_9.png"
if p9.exists():
    img = cv2.imread(str(p9))
    h, w = img.shape[:2]
    crop_x = int(w * 0.15)
    crop_y = int(h * 0.20)
    if w - 2*crop_x > 10 and h - 2*crop_y > 10:
        cropped = img[crop_y : h - crop_y, crop_x : w - crop_x]
        cv2.imwrite(str(p9), cropped)
        print(f"Shrinked ad_issue_20260606_081550_roi_9.png (New size: {cropped.shape[1]}x{cropped.shape[0]})")
