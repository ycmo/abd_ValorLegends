import cv2
from pathlib import Path
from src.vision_matcher import VisionMatcher

def main():
    base_dir = Path(r"E:\antigravity\adb_vl")
    img_path = base_dir / "switch_account" / "debug_logs" / "debug_server_em3.png"
    out_path = base_dir / "switch_account" / "matcher_preview.png"
    
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
    
    print(f"=== ROI: {roi} ===")
    
    # 畫出 ROI 綠框
    rx, ry, rw, rh = roi
    cv2.rectangle(screen, (rx, ry), (rx+rw, ry+rh), (0, 255, 0), 2)
    
    colors = [(255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255)]
    
    for i, t_name in enumerate(templates):
        t_path = base_dir / "switch_account" / "templates" / t_name
        res = matcher.match_template(screen, t_path, threshold=0.1, roi=roi, check_brightness=False)
        
        if res:
            print(f"{t_name}: 信心度 {res.confidence:.4f}, 座標 {res.center}")
            x, y, w, h = res.bbox
            # 畫出每個模板找到的位置
            cv2.rectangle(screen, (x, y), (x+w, y+h), colors[i], 2)
            cv2.putText(screen, f"{res.confidence:.2f}", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colors[i], 1)
        else:
            print(f"{t_name}: 找不到 (信心度小於 0.1)")
            
    cv2.imwrite(str(out_path), screen)
    print(f"\n✅ 預覽圖已存至: {out_path}")

if __name__ == "__main__":
    main()
