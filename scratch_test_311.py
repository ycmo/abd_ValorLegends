import cv2
from pathlib import Path
from src.vision_matcher import VisionMatcher, read_image

def main():
    base_dir = Path(r"E:\antigravity\adb_vl")
    img_path = base_dir / "switch_account" / "debug_logs" / "debug_server_311.png"
    template_path = base_dir / "switch_account" / "templates" / "008_伺服器_311.png"
    
    screen = read_image(img_path, cv2.IMREAD_COLOR)
    if screen is None:
        print("無法讀取大圖:", img_path)
        return
        
    matcher = VisionMatcher()
    
    # 全螢幕搜尋，門檻放很低
    res = matcher.match_template(screen, template_path, threshold=0.1, check_brightness=False)
    
    if res:
        print(f"找到 311 伺服器！信心度: {res.confidence:.4f}, 座標: {res.center}")
        # 也測一下在 ROI 裡面的情況
        roi = (329, 36, 627, 162)
        res_roi = matcher.match_template(screen, template_path, threshold=0.1, roi=roi, check_brightness=False)
        if res_roi:
            print(f"在 ROI 內尋找: 信心度 {res_roi.confidence:.4f}, 座標 {res_roi.center}")
        else:
            print("在 ROI 內找不到！")
    else:
        print("連 0.1 的門檻都過不了，完全找不到 311 伺服器圖片！")

if __name__ == "__main__":
    main()
