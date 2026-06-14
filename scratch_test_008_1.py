import cv2
from pathlib import Path
from src.vision_matcher import VisionMatcher, read_image

def main():
    base_dir = Path(r"E:\antigravity\adb_vl")
    img_path = base_dir / "manual_screenshots" / "帳號切換" / "008_1_確認切換伺服器.png"
    template_path = base_dir / "switch_account" / "templates" / "008_1_確認切換是_0.png"
    
    screen = read_image(img_path, cv2.IMREAD_COLOR)
    if screen is None:
        print("無法讀取大圖:", img_path)
        return
        
    matcher = VisionMatcher()
    
    # 這裡開啟 check_brightness，模擬 switch_account.py 的預設行為
    res = matcher.match_template(screen, template_path, threshold=0.1, check_brightness=True)
    
    if res:
        print(f"找到彈窗按鈕！信心度: {res.confidence:.4f}, 座標: {res.center}")
    else:
        print("加上 check_brightness 後，找不到按鈕了！")

if __name__ == "__main__":
    main()
