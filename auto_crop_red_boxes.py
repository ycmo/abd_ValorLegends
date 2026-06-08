import cv2
import numpy as np
import os
from pathlib import Path

src_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\3_reference_screens")
dst_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\1_templates\close_icons")
dst_dir.mkdir(parents=True, exist_ok=True)

count = 0

# Check both .png and .PNG
for img_path in list(src_dir.glob("*.png")) + list(src_dir.glob("*.PNG")):
    img = cv2.imread(str(img_path))
    if img is None: continue
    
    # 尋找紅色 (小畫家的正紅色 BGR 差不多是 0, 0, 255)
    lower_red = np.array([0, 0, 200])
    upper_red = np.array([60, 60, 255])
    mask = cv2.inRange(img, lower_red, upper_red)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for i, cnt in enumerate(contours):
        x, y, w, h = cv2.boundingRect(cnt)
        
        # 篩選掉太小或太大的紅框
        if w > 30 and h > 20 and w < 400 and h < 300:
            # 小畫家框線通常厚度是 2~4 pixel，我們往內縮 3 pixel 進行裁切
            t = 3
            cx, cy = x + t, y + t
            cw, ch = w - 2*t, h - 2*t
            
            if cw > 10 and ch > 10:
                cropped = img[cy:cy+ch, cx:cx+cw]
                out_name = f"auto_crop_{img_path.stem}_{i}.png"
                out_path = dst_dir / out_name
                cv2.imwrite(str(out_path), cropped)
                print(f"成功裁切: {out_name} (來自 {img_path.name})")
                count += 1

print(f"自動裁切完成！共擷取出 {count} 張新的特徵圖，並已存入 1_templates/close_icons/")
