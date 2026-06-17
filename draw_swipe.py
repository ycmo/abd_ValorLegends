import cv2
import numpy as np
import sys
import os
from pathlib import Path

# 路徑設定
template_path = r'E:\antigravity\adb_vl\AwayFromKeyboard\route_screenshots\廣告吉賽拉\02_吉賽拉_swipeV.png'
fallback_path = r'E:\antigravity\adb_vl\AwayFromKeyboard\debug\fallback_02_吉賽拉_swipe_v.png'
out_path = r'E:\antigravity\adb_vl\AwayFromKeyboard\debug\swipe_trajectory.png'

if not os.path.exists(template_path):
    print(f"找不到範本圖片: {template_path}")
    sys.exit(1)
if not os.path.exists(fallback_path):
    print(f"找不到 Fallback 圖片: {fallback_path}")
    sys.exit(1)

# 1. 解析原始範本取得 cx, cy
sys.path.insert(0, r'E:\antigravity\adb_vl')
from AwayFromKeyboard.integration_task.router import RedBoxFinder
finder = RedBoxFinder()
(cx, cy), (x, y, w, h), _ = finder.find_largest_red_box_info(Path(template_path))

# 2. 載入 fallback 圖片作為背景
img = cv2.imdecode(np.fromfile(fallback_path, dtype=np.uint8), cv2.IMREAD_COLOR)
sh, sw = img.shape[:2]

# 3. 計算目前的軌跡座標 (模擬 router.py)
start_y_fwd = min(sh - 10, max(10, int(cy + 150 * 1)))
end_y_fwd = min(sh - 10, max(10, int(cy - 150 * 1)))

start_y_rev = min(sh - 10, max(10, int(cy + 150 * -1)))
end_y_rev = min(sh - 10, max(10, int(cy - 150 * -1)))

# --- 繪圖區 ---
# 為了對比，我們在背景上標示原始紅框位置 (黃色虛線框)
cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 255), 2)
cv2.putText(img, f'Expected Target (cy={cy})', (x, max(20, y-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

# 正向滑動 (藍色)
cv2.arrowedLine(img, (cx - 40, start_y_fwd), (cx - 40, end_y_fwd), (255, 0, 0), 4, tipLength=0.1)
cv2.putText(img, f'Fwd Swipe Start', (cx - 240, start_y_fwd), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
cv2.putText(img, f'Fwd Swipe End', (cx - 240, end_y_fwd), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
cv2.circle(img, (cx - 40, start_y_fwd), 8, (255, 0, 0), -1)

# 反向滑動 (紅色)
cv2.arrowedLine(img, (cx + 40, start_y_rev), (cx + 40, end_y_rev), (0, 0, 255), 4, tipLength=0.1)
cv2.putText(img, f'Rev Swipe Start', (cx + 60, start_y_rev), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
cv2.putText(img, f'Rev Swipe End', (cx + 60, end_y_rev), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
cv2.circle(img, (cx + 40, start_y_rev), 8, (0, 0, 255), -1)

# 危險警告線 (Y=10)
cv2.line(img, (0, 10), (sw, 10), (0, 165, 255), 2)
cv2.putText(img, "WARNING: Y=10 (Notification Bar Area)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)

# 存檔
is_success, im_buf_arr = cv2.imencode(".png", img)
if is_success:
    im_buf_arr.tofile(out_path)
    print(f"✅ 軌跡圖已生成並儲存至: {out_path}")
else:
    print("❌ 存檔失敗")
