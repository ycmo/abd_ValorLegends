import cv2
from typing import Tuple

def find_template(image_path: str, template_path: str) -> Tuple[Tuple[int, int], float]:
    """
    Locates template_path inside image_path using OpenCV template matching.
    Returns: ((center_x, center_y), confidence)
    """
    img = cv2.imread(image_path)
    template = cv2.imread(template_path)
    
    if img is None:
        raise FileNotFoundError(f"Source image not found at: {image_path}")
    if template is None:
        raise FileNotFoundError(f"Template image not found at: {template_path}")
        
    h, w = template.shape[:2]
    img_h, img_w = img.shape[:2]
    
    if h > img_h or w > img_w:
        raise ValueError(
            f"Template image size ({w}x{h}) is larger than source image size ({img_w}x{img_h})"
        )
        
    # Run OpenCV template matching (TM_CCOEFF_NORMED)
    res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    
    confidence = float(max_val)
    top_left = max_loc
    
    # Calculate the center coordinate of the match
    center_x = top_left[0] + w // 2
    center_y = top_left[1] + h // 2
    
    return (center_x, center_y), confidence
