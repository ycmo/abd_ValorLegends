import cv2
import numpy as np
from pathlib import Path
import shutil

src_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\3_reference_screens")
review_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\review_crops")

if review_dir.exists():
    shutil.rmtree(review_dir)
review_dir.mkdir(parents=True, exist_ok=True)

count = 0

for img_path in list(src_dir.glob("*.png")) + list(src_dir.glob("*.PNG")):
    img = cv2.imread(str(img_path))
    if img is None: continue
    
    # 嚴格抓取紅色 (小畫家紅)
    lower_red = np.array([30, 20, 230])
    upper_red = np.array([50, 40, 255])
    mask1 = cv2.inRange(img, lower_red, upper_red)
    
    # 容許純紅
    lower_red2 = np.array([0, 0, 240])
    upper_red2 = np.array([10, 10, 255])
    mask2 = cv2.inRange(img, lower_red2, upper_red2)
    
    mask = mask1 | mask2
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for i, cnt in enumerate(contours):
        x, y, w, h = cv2.boundingRect(cnt)
        
        # 尺寸過小不可能是標註框
        if w < 15 or h < 15:
            continue
            
        sub_mask = mask[y:y+h, x:x+w]
        
        # 1. 必須同時找到上下左右四條紅色邊線 (確認是矩形，不是斜線或碎片)
        # 上下邊緣需有一定比例的紅色
        if np.sum(sub_mask[0, :] > 0) < w * 0.15: continue
        if np.sum(sub_mask[-1, :] > 0) < w * 0.15: continue
        if np.sum(sub_mask[:, 0] > 0) < h * 0.15: continue
        if np.sum(sub_mask[:, -1] > 0) < h * 0.15: continue
        
        # 2. 動態估算紅線厚度 (四條邊要接近水平/垂直)
        top = 0
        while top < h and np.sum(sub_mask[top, :] > 0) > w * 0.15:
            top += 1
            
        bottom = h - 1
        while bottom >= 0 and np.sum(sub_mask[bottom, :] > 0) > w * 0.15:
            bottom -= 1
            
        left = 0
        while left < w and np.sum(sub_mask[:, left] > 0) > h * 0.15:
            left += 1
            
        right = w - 1
        while right >= 0 and np.sum(sub_mask[:, right] > 0) > h * 0.15:
            right -= 1
            
        if top > bottom or left > right:
            # 整個都是實心紅
            continue
            
        # 3. 中間不能是大面積紅色填滿
        inner_mask = sub_mask[top:bottom+1, left:right+1]
        if inner_mask.size == 0:
            continue
        red_ratio = np.sum(inner_mask > 0) / inner_mask.size
        # 若內部仍有超過 5% 紅色，可能是填滿或是切到紅色按鈕
        if red_ratio > 0.05:
            continue
            
        # 4. 裁切後檢查 ROI 邊緣是否仍有紅色，若有就 reject
        edge_has_red = False
        if inner_mask.shape[0] > 0 and inner_mask.shape[1] > 0:
            if np.any(inner_mask[0, :] > 0) or np.any(inner_mask[-1, :] > 0):
                edge_has_red = True
            if np.any(inner_mask[:, 0] > 0) or np.any(inner_mask[:, -1] > 0):
                edge_has_red = True
                
        if edge_has_red:
            continue
            
        # 確保裁出的影像有基本尺寸
        if inner_mask.shape[0] < 5 or inner_mask.shape[1] < 5:
            continue
            
        # 成功通過所有嚴格檢查，裁切原圖
        roi_img = img[y+top : y+bottom+1, x+left : x+right+1]
        out_name = f"{img_path.stem}_roi_{i}.png"
        cv2.imwrite(str(review_dir / out_name), roi_img)
        count += 1
        print(f"Accepted: {out_name} (Size: {roi_img.shape[1]}x{roi_img.shape[0]})")

print(f"嚴格空心紅框過濾完成！共擷取出 {count} 張，放在 {review_dir} 等待確認。")
