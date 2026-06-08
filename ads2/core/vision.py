import cv2
import numpy as np
from typing import Optional

def find_green_free_button(screen: np.ndarray) -> Optional[tuple[int, int]]:
    """
    尋找純綠色的「免費」按鈕 (HSV空間)
    """
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    # 綠色的範圍 (大約 H: 35~85, S: 100~255, V: 100~255)
    lower_green = np.array([35, 100, 100])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_center = None
    best_area = 0
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 500 < area < 15000: 
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = float(w) / h
            # 按鈕通常是長方形 (寬大於高)
            if 1.5 < aspect_ratio < 6.0:
                M = cv2.moments(cnt)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    if cy > 300 and area > best_area:
                        best_area = area
                        best_center = (cx, cy)
                    
    return best_center
