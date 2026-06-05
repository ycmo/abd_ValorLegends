import cv2
import os
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
screen_path = os.path.join(_THIS_DIR, "captures", "ad_close_20260605_071601.png")
save_path = os.path.join(_THIS_DIR, "assets", "ad_close", "close_x_1.png")

screen_data = np.fromfile(screen_path, dtype=np.uint8)
img = cv2.imdecode(screen_data, cv2.IMREAD_COLOR)

# The X is in the top right corner.
# Let's crop a wider area to get the full X.
cropped = img[20:60, 910:960]
cv2.imwrite(save_path, cropped)
print(f"Saved ad close template to {save_path}")
