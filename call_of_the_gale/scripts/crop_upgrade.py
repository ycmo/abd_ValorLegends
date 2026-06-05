import cv2
import numpy as np
import os

path = os.path.join('call_of_the_gale', 'runtime_captures', '03_出發.png')
data = np.fromfile(path, dtype=np.uint8)
img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)

# Upgrade button is the blue button. Roughly x=740:860, y=390:445
# Let's crop it and save.
# But wait, looking at the image, it's roughly below the 100 onigiri text.
# The blue button has text "升級". Let's save a wide area to be safe.
crop = img[385:445, 735:865]
ok, buf = cv2.imencode('.png', crop)
with open('call_of_the_gale/assets/upgrade_button.png', 'wb') as f:
    f.write(buf.tobytes())
print("Saved upgrade_button.png")
