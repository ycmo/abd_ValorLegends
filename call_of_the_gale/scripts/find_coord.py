import cv2
import numpy as np

def read_image(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)

img = read_image('call_of_the_gale/runtime_captures/02_操作.png')
template = read_image('call_of_the_gale/runtime_captures/02_飛鏢.png')

# If template has alpha channel, handle it or convert both to BGR
if template.shape[2] == 4:
    template = template[:, :, :3]
if img.shape[2] == 4:
    img = img[:, :, :3]

res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

h, w = template.shape[:2]
center_x = max_loc[0] + w // 2
center_y = max_loc[1] + h // 2

print(f'Max Val: {max_val}')
print(f'Center Coordinate: ({center_x}, {center_y})')
