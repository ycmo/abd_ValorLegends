import cv2
import numpy as np
from pathlib import Path

def extract_red_box(img_path, out_path):
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"無法讀取圖片: {img_path}")
        
    # 嚴格抓取紅色 (雙遮罩邏輯)
    lower_red = np.array([30, 20, 230])
    upper_red = np.array([50, 40, 255])
    mask1 = cv2.inRange(img, lower_red, upper_red)
    
    # 容許純紅
    lower_red2 = np.array([0, 0, 240])
    upper_red2 = np.array([10, 10, 255])
    mask2 = cv2.inRange(img, lower_red2, upper_red2)
    
    mask = mask1 | mask2
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_area = 0
    best_rect = None
    
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 15 or h < 15:
            continue
        
        area = w * h
        if area > best_area:
            # ====== 智慧去紅邊 ======
            sub_mask = mask[y:y+h, x:x+w]
            mid_x1, mid_x2 = int(w * 0.3), int(w * 0.7)
            mid_y1, mid_y2 = int(h * 0.3), int(h * 0.7)
            
            row_sums_mid = np.sum(sub_mask[:, mid_x1:mid_x2] > 0, axis=1)
            mid_w = mid_x2 - mid_x1
            
            top = 0
            while top < h and row_sums_mid[top] > mid_w * 0.3:
                top += 1
                
            bottom = h - 1
            while bottom >= 0 and row_sums_mid[bottom] > mid_w * 0.3:
                bottom -= 1
                
            col_sums_mid = np.sum(sub_mask[mid_y1:mid_y2, :] > 0, axis=0)
            mid_h = mid_y2 - mid_y1
            
            left = 0
            while left < w and col_sums_mid[left] > mid_h * 0.3:
                left += 1
                
            right = w - 1
            while right >= 0 and col_sums_mid[right] > mid_h * 0.3:
                right -= 1
            
            if top > bottom or left > right:
                inner_x, inner_y, inner_w, inner_h = x, y, w, h
            else:
                inner_x = x + left
                inner_y = y + top
                inner_w = right - left + 1
                inner_h = bottom - top + 1
            # =======================

            best_area = area
            best_rect = (inner_x, inner_y, inner_w, inner_h)
            
    if not best_rect:
        raise ValueError(f"在 {img_path} 中找不到符合條件的紅框！")
        
    x, y, w, h = best_rect
    
    # 針對這個特定的 UI 再內縮 2 像素，確保完全沒有殘留的紅邊
    x += 2
    y += 2
    w -= 4
    h -= 4
    
    cropped = img[y:y+h, x:x+w]
    
    # 儲存
    ok, buf = cv2.imencode(".png", cropped)
    if ok:
        Path(out_path).write_bytes(buf.tobytes())
        print(f"✅ 成功擷取紅框內容並儲存至: {out_path} (大小: {w}x{h})")
    else:
        print("❌ 儲存失敗")

if __name__ == "__main__":
    img_in = r"E:\antigravity\adb_vl\manual_screenshots\帳號切換\002_點伺服器.png"
    img_out = r"E:\antigravity\adb_vl\switch_account\templates\002_點伺服器_0.png"
    extract_red_box(img_in, img_out)
