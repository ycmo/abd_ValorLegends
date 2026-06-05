import os
import cv2
import easyocr
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
_MANUAL_DIR = os.path.join(_PROJECT_ROOT, "manual_screenshots", "廣告")
_ASSETS_ENTRY = os.path.join(_THIS_DIR, "assets", "entry")

def main():
    print("Loading EasyOCR...")
    reader = easyocr.Reader(['ch_tra'], gpu=False)
    os.makedirs(_ASSETS_ENTRY, exist_ok=True)

    targets = [
        {"file": "001_主畫面.png", "text": "王國事件", "save": "nav_kingdom.png"},
        {"file": "002_王國事件.png", "text": "異界奇聞", "save": "nav_otherworld.png"},
        {"file": "002_異界奇聞.png", "text": "免費", "save": "btn_free_ad.png"}
    ]

    for target in targets:
        img_path = os.path.join(_MANUAL_DIR, target["file"])
        if not os.path.exists(img_path):
            print(f"[Error] Image not found: {img_path}")
            continue

        print(f"[Info] Identifying '{target['text']}' in {target['file']}...")
        # cv2.imread cannot handle Chinese paths on Windows, use imdecode
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f"[Error] Failed to read image data from: {img_path}")
            continue
        
        # 進行 OCR 辨識
        results = reader.readtext(img)
        found = False
        
        for (bbox, text, prob) in results:
            if target["text"] in text:
                print(f"  [OK] Found '{text}' (conf: {prob:.2f})")
                
                # bbox 格式: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                x_coords = [p[0] for p in bbox]
                y_coords = [p[1] for p in bbox]
                x_min, x_max = int(min(x_coords)), int(max(x_coords))
                y_min, y_max = int(min(y_coords)), int(max(y_coords))
                
                # 往外擴張一點點，把按鈕圖示包進來
                # 例如左側圖示，所以 x_min 往左邊多抓一點
                pad_x = 40
                pad_y = 15
                x1 = max(0, x_min - pad_x)
                x2 = min(img.shape[1], x_max + pad_x)
                y1 = max(0, y_min - pad_y)
                y2 = min(img.shape[0], y_max + pad_y)
                
                cropped = img[y1:y2, x1:x2]
                
                save_path = os.path.join(_ASSETS_ENTRY, target["save"])
                cv2.imwrite(save_path, cropped)
                print(f"  [Save] Cropped and saved as: {target['save']}")
                found = True
                break
                
        if not found:
            print(f"  [Warning] Could not find '{target['text']}' in {target['file']}")

if __name__ == "__main__":
    main()
