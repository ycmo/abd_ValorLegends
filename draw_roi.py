import cv2
import numpy as np
import sys
import os
from pathlib import Path

# 路徑設定
template_path = r'E:\antigravity\adb_vl\AwayFromKeyboard\route_screenshots\廣告吉賽拉\02_吉賽拉_swipeV.png'
fallback_path = r'E:\antigravity\adb_vl\AwayFromKeyboard\debug\fallback_02_吉賽拉_swipe_v.png'
out_path = r'E:\antigravity\adb_vl\AwayFromKeyboard\debug\roi_debug.png'

if not os.path.exists(template_path):
    print(f"找不到範本圖片: {template_path}")
    sys.exit(1)
if not os.path.exists(fallback_path):
    print(f"找不到 Fallback 圖片: {fallback_path}")
    sys.exit(1)

# 1. 解析原始範本取得 x, y, w, h
sys.path.insert(0, r'E:\antigravity\adb_vl')
from AwayFromKeyboard.integration_task.router import RedBoxFinder
finder = RedBoxFinder()
(cx, cy), (x, y, w, h), _ = finder.find_largest_red_box_info(Path(template_path))

# 2. 載入 fallback 圖片作為背景
img = cv2.imdecode(np.fromfile(fallback_path, dtype=np.uint8), cv2.IMREAD_COLOR)
sh, sw = img.shape[:2]

# 3. 模擬 router.py 內的 ROI 計算邏輯 (針對 is_swipe_v)
roi_x1 = max(0, x - 50)
roi_x2 = min(sw, x + w + 50)
roi_y1 = 0
roi_y2 = sh

# --- 繪圖區 ---

# 建立一個透明的覆蓋層用來畫 ROI 區域
overlay = img.copy()
cv2.rectangle(overlay, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), -1)
# 混合透明度，讓 ROI 區塊呈現半透明綠色
cv2.addWeighted(overlay, 0.2, img, 0.8, 0, img)

# 畫出 ROI 的邊界框
cv2.rectangle(img, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 3)
cv2.putText(img, f'ROI Search Area', (roi_x1, roi_y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
cv2.putText(img, f'(x1={roi_x1}, x2={roi_x2}, y1=0, y2={sh})', (roi_x1, roi_y1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

# 為了對比，畫出目標原來的紅框預期位置 (黃色虛線框)
cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 255), 2)
cv2.putText(img, 'Original Target Position', (x, max(20, y-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

# 存檔
is_success, im_buf_arr = cv2.imencode(".png", img)
if is_success:
    im_buf_arr.tofile(out_path)
    print(f"ROI圖已生成並儲存至: {out_path}")
else:
    print("存檔失敗")
