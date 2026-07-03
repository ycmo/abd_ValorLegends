import cv2
import numpy as np
import os

def main():
    target_dir = os.path.dirname(os.path.abspath(__file__))
    frames_dir = os.path.join(target_dir, "frames")
    templates_dir = os.path.join(target_dir, "templates")
    
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        
    image_path = os.path.join(frames_dir, "ScreenRecording_06-24-2026 05-46-30_1_frame_0005.jpg")
    img = cv2.imread(image_path)
    if img is None:
        print(f"Error reading {image_path}")
        return
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(
        gray, 
        cv2.HOUGH_GRADIENT, 
        dp=1.2, 
        minDist=100, 
        param1=50, 
        param2=30, 
        minRadius=30, 
        maxRadius=80
    )
    
    screw_saved = False
    hole_saved = False
    
    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        for (x, y, r) in circles:
            if screw_saved and hole_saved:
                break
                
            # Add a bit of padding if possible, or just exact radius
            y_start = max(0, y - r)
            y_end = min(img.shape[0], y + r)
            x_start = max(0, x - r)
            x_end = min(img.shape[1], x + r)
            
            roi_gray = gray[y_start:y_end, x_start:x_end]
            roi_color = img[y_start:y_end, x_start:x_end]
            
            if roi_gray.shape[0] == 0 or roi_gray.shape[1] == 0:
                continue
                
            center_roi = roi_gray[int(roi_gray.shape[0]*0.2):int(roi_gray.shape[0]*0.8), int(roi_gray.shape[1]*0.2):int(roi_gray.shape[1]*0.8)]
            if center_roi.shape[0] == 0 or center_roi.shape[1] == 0:
                continue
                
            edges = cv2.Canny(center_roi, 50, 150)
            edge_density = np.sum(edges > 0) / (center_roi.shape[0] * center_roi.shape[1] + 1e-5)
            
            if edge_density > 0.05 and not screw_saved:
                cv2.imwrite(os.path.join(templates_dir, "screw_template.png"), roi_color)
                screw_saved = True
                print("Saved screw_template.png")
            elif edge_density <= 0.05 and not hole_saved:
                cv2.imwrite(os.path.join(templates_dir, "hole_template.png"), roi_color)
                hole_saved = True
                print("Saved hole_template.png")

if __name__ == "__main__":
    main()
