import cv2
import numpy as np
import sys
from pathlib import Path

def process_directory(dir_path: str):
    src_dir = Path(dir_path)
    if not src_dir.exists() or not src_dir.is_dir():
        print(f"找不到資料夾: {src_dir}")
        return
        
    dst_dir = src_dir / 'transparent_output'
    dst_dir.mkdir(exist_ok=True)
    
    count = 0
    # 支援 .png 與 .PNG
    for f in list(src_dir.glob('*.png')) + list(src_dir.glob('*.PNG')):
        data = np.fromfile(str(f), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if img is None: continue
        
        # 若無透明通道則加上
        if len(img.shape) == 3 and img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            
        # 尋找近乎純白的像素 (R,G,B >= 250)
        white_mask = (img[:,:,0] >= 250) & (img[:,:,1] >= 250) & (img[:,:,2] >= 250)
        
        # 將白色像素去背 (Alpha=0)
        img[white_mask, 3] = 0
        
        # 輸出檔案
        out_path = dst_dir / f.name
        ok, buf = cv2.imencode('.png', img)
        if ok:
            out_path.write_bytes(buf.tobytes())
            count += 1
            print(f"✅ 去背成功: {f.name}")
            
    print(f"\n處理完畢！共轉換了 {count} 張圖片。")
    print(f"檔案已儲存至: {dst_dir}")

if __name__ == "__main__":
    print("===========================================")
    print("       小畫家塗白 -> 完美去背轉換工具      ")
    print("===========================================")
    print("請輸入你要處理的「資料夾路徑」")
    print("例如: E:\\antigravity\\adb_vl\\ads2\\assets\\場景\\看廣告主畫面")
    user_input = input(">> 路徑: ").strip()
    
    # 移除頭尾可能出現的引號
    if user_input.startswith('"') and user_input.endswith('"'):
        user_input = user_input[1:-1]
    elif user_input.startswith("'") and user_input.endswith("'"):
        user_input = user_input[1:-1]
        
    if user_input:
        process_directory(user_input)
    else:
        print("未輸入路徑，結束程式。")
    
    # 讓視窗不會馬上關閉
    input("\n按 Enter 鍵結束...")
