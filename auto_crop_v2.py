import cv2
import numpy as np
import os
from pathlib import Path
import shutil

src_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\3_reference_screens")
dst_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\1_templates\close_icons")

# 清除之前錯誤裁切的檔案 (自動產生的)
for f in dst_dir.glob("auto_crop_*.png"):
    f.unlink()

count = 0

for img_path in list(src_dir.glob("*.png")) + list(src_dir.glob("*.PNG")):
    img = cv2.imread(str(img_path))
    if img is None: continue
    
    # 尋找特定的紅筆顏色 (小畫家/剪取工具預設紅: BGR [36, 28, 237])
    # 我們給予極小的容差，避免誤判到遊戲中本來的紅色元素
    lower_red = np.array([30, 20, 230])
    upper_red = np.array([45, 35, 245])
    mask = cv2.inRange(img, lower_red, upper_red)
    
    # 也可以加上純紅色的容差 (0, 0, 255)
    lower_red2 = np.array([0, 0, 240])
    upper_red2 = np.array([10, 10, 255])
    mask2 = cv2.inRange(img, lower_red2, upper_red2)
    
    final_mask = mask | mask2
    
    contours, _ = cv2.findContours(final_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for i, cnt in enumerate(contours):
        x, y, w, h = cv2.boundingRect(cnt)
        
        # 篩選掉太小或太大的紅框
        if w > 15 and h > 15 and w < 400 and h < 300:
            # 取得框框內的影像與遮罩
            box_img = img[y:y+h, x:x+w].copy()
            box_mask = final_mask[y:y+h, x:x+w]
            
            # 由於邊框有厚度，我們由外向內把有紅色的行/列削掉
            top, bottom, left, right = 0, h, 0, w
            
            # 削掉上面
            while top < bottom and np.any(box_mask[top, :]):
                top += 1
            # 削掉下面
            while bottom > top and np.any(box_mask[bottom-1, :]):
                bottom -= 1
            # 削掉左邊
            while left < right and np.any(box_mask[:, left]):
                left += 1
            # 削掉右邊
            while right > left and np.any(box_mask[:, right-1]):
                right -= 1
                
            # 為了去除抗鋸齒的殘留邊緣，額外再往內縮 2 像素
            trim = 2
            top += trim
            bottom -= trim
            left += trim
            right -= trim
            
            cw = right - left
            ch = bottom - top
            
            if cw > 5 and ch > 5:
                cropped = box_img[top:bottom, left:right]
                out_name = f"auto_crop_v2_{img_path.stem}_{i}.png"
                out_path = dst_dir / out_name
                cv2.imwrite(str(out_path), cropped)
                print(f"精準裁切: {out_name} (尺寸: {cw}x{ch})")
                count += 1

print(f"自動裁切完成！共擷取出 {count} 張新的特徵圖。")
