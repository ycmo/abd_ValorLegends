import os
import time
import subprocess
import cv2
import numpy as np
from pathlib import Path
import shutil

def capture_screen(filepath: Path):
    print("正在透過 ADB 擷取模擬器畫面...")
    try:
        # 使用 exec-out 避免 \r\n 換行符號損壞二進位圖片檔
        result = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"], 
            capture_output=True, 
            check=True
        )
        with open(filepath, "wb") as f:
            f.write(result.stdout)
        print(f"✅ 截圖成功！")
        return True
    except Exception as e:
        print(f"❌ 截圖失敗！請確認模擬器是否已啟動，且 ADB 連線正常。")
        print(f"錯誤訊息: {e}")
        return False

def open_paint_and_wait(filepath: Path):
    print("\n--------------------------------------------------")
    print("【操作指引】")
    print("1. 正在為您開啟小畫家...")
    print("2. 請在小畫家中使用「矩形」工具，選擇「純色/無填滿」，並選用「紅色」。")
    print("3. 在你想教系統辨識的按鈕上，畫上精準的紅色空心矩形。")
    print("4. 畫完後直接按 Ctrl + S 存檔，然後關閉小畫家。")
    print("--------------------------------------------------")
    try:
        # 使用 run 會阻塞程式，直到使用者關閉小畫家
        print("\n[等待操作] 請在小畫家畫完紅框、存檔，然後【直接關閉小畫家】，程式就會自動繼續！")
        subprocess.run(["mspaint", str(filepath)])
    except Exception as e:
        print(f"無法自動開啟小畫家，請手動開啟檔案。錯誤: {e}")

def crop_red_box(filepath: Path):
    img = cv2.imread(str(filepath))
    if img is None:
        print("無法讀取圖片！")
        return []
        
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
    
    found_rois = []
    for i, cnt in enumerate(contours):
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 15 or h < 15:
            continue
            
        sub_mask = mask[y:y+h, x:x+w]
        mid_x1, mid_x2 = int(w * 0.3), int(w * 0.7)
        mid_y1, mid_y2 = int(h * 0.3), int(h * 0.7)
        
        if np.sum(sub_mask[0, mid_x1:mid_x2] > 0) < (mid_x2 - mid_x1) * 0.3: continue
        if np.sum(sub_mask[-1, mid_x1:mid_x2] > 0) < (mid_x2 - mid_x1) * 0.3: continue
        if np.sum(sub_mask[mid_y1:mid_y2, 0] > 0) < (mid_y2 - mid_y1) * 0.3: continue
        if np.sum(sub_mask[mid_y1:mid_y2, -1] > 0) < (mid_y2 - mid_y1) * 0.3: continue
        
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
            continue
            
        inner_mask = sub_mask[top:bottom+1, left:right+1]
        if inner_mask.size == 0:
            continue
        red_ratio = np.sum(inner_mask > 0) / inner_mask.size
        if red_ratio > 0.05:
            continue
            
        edge_has_red = False
        if inner_mask.shape[0] > 0 and inner_mask.shape[1] > 0:
            if np.any(inner_mask[0, :] > 0) or np.any(inner_mask[-1, :] > 0): edge_has_red = True
            if np.any(inner_mask[:, 0] > 0) or np.any(inner_mask[:, -1] > 0): edge_has_red = True
                
        if edge_has_red:
            continue
            
        if inner_mask.shape[0] < 5 or inner_mask.shape[1] < 5:
            continue
            
        # 成功通過所有檢查，裁切原圖
        roi_img = img[y+top : y+bottom+1, x+left : x+right+1]
        found_rois.append(roi_img)

    if found_rois:
        return found_rois
    else:
        print("❌ 找不到符合條件的紅色空心框，請確認紅框是否繪製正確 (不要太細、太粗，且必須是純紅空心)。")
        return []

def main():
    # 動態取得專案根目錄 (magic_shop 的上一層)
    current_dir = Path(__file__).parent
    workspace = current_dir.parent
    
    # 建立暫存資料夾
    temp_dir = current_dir / "temp_captures"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    full_img_path = temp_dir / f"full_{timestamp}.png"
    cropped_img_path = temp_dir / f"cropped_{timestamp}.png"
    
    # 步驟 1：截圖
    if not capture_screen(full_img_path):
        return
        
    # 步驟 2：標記 (開啟小畫家)
    open_paint_and_wait(full_img_path)
    
    # 步驟 3：裁切
    print("\n正在尋找紅框並裁切...")
    rois = crop_red_box(full_img_path)
    if not rois:
        return
        
    print(f"✅ 共找到 {len(rois)} 個符合的紅框區域！")
    
    # 步驟 4 & 5：依序確認並存檔
    for idx, roi in enumerate(rois):
        print(f"\n==================================================")
        print(f"正在處理第 {idx+1}/{len(rois)} 個裁切圖片...")
        print(f"==================================================")
        
        cropped_img_path = temp_dir / f"cropped_{timestamp}_{idx}.png"
        cv2.imwrite(str(cropped_img_path), roi)
        
        # 步驟 4：確認
        print("正在開啟圖片供您確認...")
        subprocess.Popen(["mspaint", str(cropped_img_path)])
        
        while True:
            confirm = input("圖片確認無誤嗎？([Enter]確認 / n取消 / skip跳過): ").strip().lower()
            if confirm in ['', 'y', 'yes', '確認']:
                confirm = 'y'
                break
            elif confirm in ['n', 'no', '取消']:
                print("取消整個腳本操作。")
                return
            elif confirm in ['skip', '跳過']:
                print("跳過這張圖片。")
                break
                
        if confirm in ['skip', '跳過']:
            continue
            
        # 步驟 5：分類與存檔
        print("\n請輸入這張圖片的命名 (例如: buy_btn 或 items/purple_bead)")
        print("程式會自動將其儲存至 magic_shop/assets/您的命名.png")
        target_label = input("命名: ").strip()
        
        if not target_label:
            print("未輸入命名，跳過這張圖片的存檔。")
            continue
            
        target_path = current_dir / "assets" / f"{target_label}.png"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy(cropped_img_path, target_path)
        print(f"🎉 圖片已成功存檔至: {target_path}")

    print("\n✅ 所有裁切圖片處理完畢！")

if __name__ == "__main__":
    main()
