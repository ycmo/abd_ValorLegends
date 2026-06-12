import cv2
import numpy as np
from pathlib import Path

def process_all_images():
    src_dir = Path(r"E:\antigravity\adb_vl\manual_screenshots\帳號切換")
    out_dir = Path(__file__).resolve().parent / "templates"
    out_dir.mkdir(exist_ok=True)
    
    # 清空舊的 templates
    for f in out_dir.glob("*.png"):
        f.unlink()

    count = 0
    for img_path in sorted(src_dir.glob("*.png")):
        # Read image supporting unicode paths
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
            
        lower_red = np.array([30, 20, 230])
        upper_red = np.array([50, 40, 255])
        mask1 = cv2.inRange(img, lower_red, upper_red)
        
        lower_red2 = np.array([0, 0, 240])
        upper_red2 = np.array([10, 10, 255])
        mask2 = cv2.inRange(img, lower_red2, upper_red2)
        
        mask = mask1 | mask2
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        boxes = []
        for cnt in contours:
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
                # If there's still red on the edge, aggressively strip 2 more pixels
                top += 2
                bottom -= 2
                left += 2
                right -= 2
                
            if bottom - top < 5 or right - left < 5:
                continue
                
            roi_img = img[y+top : y+bottom+1, x+left : x+right+1]
            boxes.append((y, x, roi_img))

        # Sort top-to-bottom
        boxes.sort(key=lambda b: b[0])
        
        for i, (y, x, roi_img) in enumerate(boxes):
            out_name = f"{img_path.stem}_{i}.png"
            out_p = out_dir / out_name
            ok, buf = cv2.imencode(".png", roi_img)
            if ok:
                out_p.write_bytes(buf.tobytes())
                count += 1
                print(f"Extracted {out_name} (Size: {roi_img.shape[1]}x{roi_img.shape[0]})")

if __name__ == "__main__":
    process_all_images()
    print("Cropping finished.")
