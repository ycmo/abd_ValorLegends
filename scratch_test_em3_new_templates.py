import cv2
import os
from pathlib import Path
from src.vision_matcher import VisionMatcher

def main():
    base_dir = Path(r"E:\antigravity\adb_vl")
    task_dir = base_dir / "switch_account"
    debug_dir = task_dir / "debug"
    
    img_path = task_dir / "debug_logs" / "debug_server_em3.png"
    out_path = debug_dir / "matcher_preview_001.png"
    
    screen = cv2.imread(str(img_path))
    if screen is None:
        print("無法讀取圖片:", img_path)
        return
        
    # Set ROI to None to scan the whole screen and find the true coordinates
    roi = None
    templates = [
        "008_伺服器_311.png",
        "008_伺服器_em3.png"
    ]
    
    matcher = VisionMatcher()
    
    colors = [(255, 0, 0), (0, 0, 255)] # Blue for 311, Red for em3
    
    for i, t_name in enumerate(templates):
        t_path = debug_dir / t_name
        
        # roi=None to find true position
        res = matcher.match_template(screen, t_path, threshold=0.1, roi=roi, check_brightness=False)
        
        if res:
            short_name = t_name.replace("008_伺服器_", "").replace(".png", "")
            text = f"{short_name} ({res.confidence:.4f})"
            cx, cy = res.center
            print(f"Found {t_name} at bbox {res.bbox}")
            
            # Draw bbox
            rx, ry, rw, rh = res.bbox
            cv2.rectangle(screen, (rx, ry), (rx+rw, ry+rh), colors[i], 2)
            cv2.putText(screen, text, (rx, ry-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[i], 2)
            
    cv2.imwrite(str(out_path), screen)
    print("success")

if __name__ == "__main__":
    main()
