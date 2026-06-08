import cv2
import numpy as np
import os
from pathlib import Path

base_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\1_templates\close_icons")

# 1. 刪除錯誤的 manual_check
for f in ["manual_check_20260605_102938_roi_1.png", "manual_check2_20260605_103009_roi_0.png"]:
    p = base_dir / f
    if p.exists():
        p.unlink()
        print(f"Deleted {f}")

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
    top, bottom, left, right = 0, h, 0, w
    
    # 從邊緣往內縮，直到沒有紅色
    while top < bottom and np.any(mask[top, :]): top += 1
    while bottom > top and np.any(mask[bottom-1, :]): bottom -= 1
    while left < right and np.any(mask[:, left]): left += 1
    while right > left and np.any(mask[:, right-1]): right -= 1
    
    # 再往內縮 1 pixel 確保乾淨
    if top < bottom: top += 1
    if bottom > top: bottom -= 1
    if left < right: left += 1
    if right > left: right -= 1
    
    cropped = img[top:bottom, left:right]
    cv2.imwrite(str(p), cropped)
    print(f"Fixed {f} (New size: {cropped.shape[1]}x{cropped.shape[0]})")

# 3. 縮小 ad_issue_20260606_081550_roi_9.png
p9 = base_dir / "ad_issue_20260606_081550_roi_9.png"
if p9.exists():
    img = cv2.imread(str(p9))
    h, w = img.shape[:2]
    # 縮小範圍，例如上下左右各裁掉 20%
    crop_x = int(w * 0.15)
    crop_y = int(h * 0.20)
    cropped = img[crop_y : h - crop_y, crop_x : w - crop_x]
    cv2.imwrite(str(p9), cropped)
    print(f"Shrinked ad_issue_20260606_081550_roi_9.png (New size: {cropped.shape[1]}x{cropped.shape[0]})")
