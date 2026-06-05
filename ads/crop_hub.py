import cv2
import os
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
screen_path = os.path.join(_THIS_DIR, "captures", "check_back_20260605_075109.png")
save_path = os.path.join(_THIS_DIR, "assets", "entry", "hub_anchor.png")

screen_data = np.fromfile(screen_path, dtype=np.uint8)
img = cv2.imdecode(screen_data, cv2.IMREAD_COLOR)

# The text "廣告特權會員卡" is around y: 180-230, x: 230-390
cropped = img[180:230, 230:390]
cv2.imwrite(save_path, cropped)
print(f"Saved hub anchor to {save_path}")
