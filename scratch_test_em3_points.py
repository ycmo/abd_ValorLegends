import cv2
import os
from pathlib import Path
from src.vision_matcher import VisionMatcher

def main():
    base_dir = Path(r"E:\antigravity\adb_vl")
    task_dir = base_dir / "switch_account"
    debug_dir = task_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    
    img_path = task_dir / "debug_logs" / "debug_server_em3.png"
    out_path = debug_dir / "matcher_preview.png"
    
    screen = cv2.imread(str(img_path))
    if screen is None:
        print("無法讀取圖片:", img_path)
        return
        
    roi = (329, 36, 627, 162)
    templates = [
        "008_伺服器列表_311_1.png",
        "008_伺服器列表_311_2.png",
        "008_伺服器列表_em3_1.png",
        "008_伺服器列表_em3_2.png"
    ]
    
    matcher = VisionMatcher()
    
    # 畫出 ROI 綠框
    rx, ry, rw, rh = roi
    cv2.rectangle(screen, (rx, ry), (rx+rw, ry+rh), (0, 255, 0), 2)
    cv2.putText(screen, "ROI Limit", (rx, ry-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    colors = [(255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255)]
    
    for i, t_name in enumerate(templates):
        t_path = task_dir / "templates" / t_name
        res = matcher.match_template(screen, t_path, threshold=0.1, roi=roi, check_brightness=False)
        
        if res:
            # 取出簡寫檔名，例如 311_1
            short_name = t_name.replace("008_伺服器列表_", "").replace(".png", "")
            text = f"{short_name} ({res.confidence:.4f})"
            cx, cy = res.center
            
            # 在中心點畫實心圓點
            cv2.circle(screen, (cx, cy), 6, colors[i], -1)
            
            # 依據 index 讓文字稍微錯開，避免疊在一起
            offset_y = cy - 40 + (i * 25)
            # 給文字加點黑色外框讓它在淺色背景更清楚
            cv2.putText(screen, text, (cx - 30, offset_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
            cv2.putText(screen, text, (cx - 30, offset_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[i], 2)
            
    cv2.imwrite(str(out_path), screen)
    print("success")

if __name__ == "__main__":
    main()
