import cv2
import numpy as np
import os
import glob

def detect_screws_and_holes(image_path, output_path):
    img = cv2.imread(image_path)
    if img is None:
        return
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Use HoughCircles to find circular objects (screws and holes)
    # We may need to tune parameters based on the image size
    # Image size is around 2360x1640 based on typical iPads, wait let's just use generic params
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
    
    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        for (x, y, r) in circles:
            # Extract the ROI to classify if it's a screw or a hole
            roi = gray[max(0, y-r):min(gray.shape[0], y+r), max(0, x-r):min(gray.shape[1], x+r)]
            
            # Simple heuristic: Screws have a cross (+) which has strong edges inside
            # Empty holes are just a dark outline with background inside
            # Let's just calculate edge density in the center of the ROI
            if roi.shape[0] == 0 or roi.shape[1] == 0:
                continue
                
            center_roi = roi[int(roi.shape[0]*0.2):int(roi.shape[0]*0.8), int(roi.shape[1]*0.2):int(roi.shape[1]*0.8)]
            edges = cv2.Canny(center_roi, 50, 150)
            edge_density = np.sum(edges > 0) / (center_roi.shape[0] * center_roi.shape[1] + 1e-5)
            
            # Draw circle
            if edge_density > 0.05:
                # Likely a screw (red)
                cv2.circle(img, (x, y), r, (0, 0, 255), 4)
                cv2.putText(img, "Screw", (x - 20, y - r - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            else:
                # Likely an empty hole (green)
                cv2.circle(img, (x, y), r, (0, 255, 0), 4)
                cv2.putText(img, "Hole", (x - 20, y - r - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                
    cv2.imwrite(output_path, img)
    print(f"Processed {image_path} -> {output_path}")

def main():
    target_dir = os.path.dirname(os.path.abspath(__file__))
    frames_dir = os.path.join(target_dir, "frames")
    debug_dir = os.path.join(target_dir, "debug_cv")
    
    if not os.path.exists(debug_dir):
        os.makedirs(debug_dir)
        
    frames = glob.glob(os.path.join(frames_dir, "*_frame_0005.jpg")) + glob.glob(os.path.join(frames_dir, "*_frame_0010.jpg"))
    for f in frames:
        out_name = os.path.basename(f)
        detect_screws_and_holes(f, os.path.join(debug_dir, out_name))

if __name__ == "__main__":
    main()
