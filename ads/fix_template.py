import cv2
import os
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
screen_path = os.path.join(_THIS_DIR, "captures", "test_screen_20260605_071116.png")
save_path = os.path.join(_THIS_DIR, "assets", "entry", "btn_free_ad.png")

screen_data = np.fromfile(screen_path, dtype=np.uint8)
img = cv2.imdecode(screen_data, cv2.IMREAD_COLOR)

# Center is (479, 364). Crop tightly around it.
# Let's crop a 80x24 region.
# x: 479 - 40 = 439, x: 479 + 40 = 519
# y: 364 - 12 = 352, y: 364 + 12 = 376

cropped = img[352:376, 439:519]
cv2.imwrite(save_path, cropped)
print(f"Saved tighter template to {save_path}")
