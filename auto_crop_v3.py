import cv2
import numpy as np
import os
from pathlib import Path

src_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\3_reference_screens")
dst_dir = Path(r"E:\antigravity\adb_vl\ads2\assets\1_templates\close_icons")

count = 0

for img_path in list(src_dir.glob("*.png")) + list(src_dir.glob("*.PNG")):
    img = cv2.imread(str(img_path))
    if img is None: continue
    
    # 尋找特定的紅筆顏色 (小畫家預設紅: BGR [36, 28, 237])
    lower_red = np.array([30, 20, 230])
    upper_red = np.array([45, 35, 245])
    mask = cv2.inRange(img, lower_red, upper_red)
    
    # 使用 RETR_CCOMP 找出所有輪廓及其內外層關係 (Hierarchy)
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    
    if hierarchy is None:
        continue
        
    for i, cnt in enumerate(contours):
        parent_idx = hierarchy[0][i][3]
        
        # parent_idx != -1 代表這個輪廓是「某個外框的內層洞」
        # 這正是使用者畫出的「紅框」內部的區域！
        if parent_idx != -1:
            # 取得這個內層洞的 bounding box (完全避開了紅線)
            x, y, w, h = cv2.boundingRect(cnt)
            
            # 確保裁切範圍合理
            if w > 10 and h > 10 and w < 400 and h < 300:
                # 為了去除可能的邊緣抗鋸齒殘留，可以選擇往內縮 1 pixel (如果太大再縮)
                trim = 1
                if w > 15 and h > 15:
                    x += trim
                    y += trim
                    w -= 2*trim
                    h -= 2*trim
                    
                cropped = img[y:y+h, x:x+w]
                out_name = f"auto_crop_v3_{img_path.stem}_{i}.png"
                out_path = dst_dir / out_name
                cv2.imwrite(str(out_path), cropped)
                print(f"精準內框裁切: {out_name} (尺寸: {w}x{h}, 來自 {img_path.name})")
                count += 1

print(f"自動裁切完成！共擷取出 {count} 張完美的特徵圖。")
