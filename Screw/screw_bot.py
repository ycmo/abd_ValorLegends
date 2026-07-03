import cv2
import numpy as np
import time
import os
import sys
import argparse
from datetime import datetime

# Add parent directory to path so we can import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.adb_controller import DeviceController
except ImportError:
    print("Warning: Could not import src.adb_controller. Make sure you run this from the project root or the file exists.")
    class DeviceController:
        def tap(self, x, y): pass
        def screenshot(self): return np.zeros((100, 100, 3), dtype=np.uint8)

class ScrewBot:
    def __init__(self, adb_controller, templates_dir: str = None, debug_actions: bool = False):
        self.adb = adb_controller
        self.debug_actions = debug_actions
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        
        if templates_dir is None:
            self.templates_dir = os.path.join(self.base_dir, "templates")
        else:
            self.templates_dir = templates_dir
            
        if self.debug_actions:
            self.debug_dir = os.path.join(self.base_dir, "debug_actions")
            if not os.path.exists(self.debug_dir):
                os.makedirs(self.debug_dir)
                
        screw_path = os.path.join(self.templates_dir, "screw_template.png")
        hole_path = os.path.join(self.templates_dir, "hole_template.png")
        
        if os.path.exists(screw_path):
            self.screw_template = cv2.imread(screw_path, cv2.IMREAD_GRAYSCALE)
        else:
            self.screw_template = None
            
        if os.path.exists(hole_path):
            self.hole_template = cv2.imread(hole_path, cv2.IMREAD_GRAYSCALE)
        else:
            self.hole_template = None
            
        if self.screw_template is None or self.hole_template is None:
            print(f"Warning: Templates not found in {self.templates_dir}. Please ensure templates are generated.")

    def detect_objects(self, image_gray, template, threshold=0.7, scales=[0.8, 0.9, 1.0, 1.1, 1.2]):
        """
        Multi-scale template matching with Non-Maximum Suppression.
        Returns a list of (x, y) center coordinates.
        """
        if template is None:
            return []
            
        found_points = []
        template_h, template_w = template.shape[:2]
        
        for scale in scales:
            resized_template = cv2.resize(template, (int(template_w * scale), int(template_h * scale)))
            h, w = resized_template.shape[:2]
            
            if h > image_gray.shape[0] or w > image_gray.shape[1]:
                continue
                
            res = cv2.matchTemplate(image_gray, resized_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)
            
            for pt in zip(*loc[::-1]):
                center_x = pt[0] + w // 2
                center_y = pt[1] + h // 2
                score = res[pt[1], pt[0]]
                found_points.append((center_x, center_y, score, w, h))
                
        # Apply NMS
        if not found_points:
            return []
            
        found_points.sort(key=lambda x: x[2], reverse=True)
        final_points = []
        
        for pt in found_points:
            keep = True
            for f_pt in final_points:
                dist = np.sqrt((pt[0] - f_pt[0])**2 + (pt[1] - f_pt[1])**2)
                if dist < (template_w * 0.5):
                    keep = False
                    break
            if keep:
                final_points.append((pt[0], pt[1]))
                
        return final_points

    def detect_screws_and_holes(self, image):
        """
        Detect all screws and holes in the image.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        screws = self.detect_objects(gray, self.screw_template, threshold=0.7)
        holes = self.detect_objects(gray, self.hole_template, threshold=0.6) 
        return screws, holes

    def save_debug_image(self, image, prefix, s_pos, h_pos):
        """
        Saves a screenshot with visual markers for debugging.
        """
        if not self.debug_actions:
            return
            
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{prefix}_{timestamp}_S{s_pos[0]}_{s_pos[1]}_to_H{h_pos[0]}_{h_pos[1]}.jpg"
        filepath = os.path.join(self.debug_dir, filename)
        
        debug_img = image.copy()
        cv2.circle(debug_img, s_pos, 30, (0, 0, 255), 4) # Red for target screw
        cv2.circle(debug_img, h_pos, 30, (0, 255, 0), 4) # Green for target hole
        
        cv2.imwrite(filepath, debug_img)
        print(f"Saved debug image: {filename}")

    def is_screw_still_there(self, old_screw_pos, new_screws_list, tolerance=15):
        """
        Checks if the screw is still at its original position after a move attempt.
        """
        for ns in new_screws_list:
            dist = np.sqrt((old_screw_pos[0] - ns[0])**2 + (old_screw_pos[1] - ns[1])**2)
            if dist <= tolerance:
                return True
        return False

    def run(self):
        """
        Main trial-and-error solver loop.
        """
        print(f"Starting ScrewBot... (Debug Actions: {self.debug_actions})")
        while True:
            try:
                screen = self.adb.screenshot()
            except Exception as e:
                print(f"Failed to get screenshot: {e}")
                break
                
            # Dynamic Hole Building: Every loop we scan fresh
            screws, holes = self.detect_screws_and_holes(screen)
            print(f"\n--- New Board State ---")
            print(f"Detected {len(screws)} screws and {len(holes)} holes.")
            
            if not screws:
                print("No more screws detected. Level completely cleared!")
                break
                
            if not holes:
                # If a plate drops and covers all holes, we are deadlocked.
                print("No empty holes available. Stuck or Game Over!")
                # Here we could restart the level if we had the adb coordinates for the restart button
                break
                
            moved = False
            for s in screws:
                for h in holes:
                    print(f"Trying to move screw at {s} to hole at {h}...")
                    self.save_debug_image(screen, "before", s, h)
                    
                    self.adb.tap(s[0], s[1])
                    time.sleep(0.3)
                    self.adb.tap(h[0], h[1])
                    
                    # Wait for plate to physically swing and drop, exposing new holes or covering old ones
                    time.sleep(2.0) 
                    
                    try:
                        new_screen = self.adb.screenshot()
                    except Exception as e:
                        print(f"Failed to get new screenshot: {e}")
                        break
                        
                    self.save_debug_image(new_screen, "after", s, h)
                    
                    # Re-detect the new state
                    new_screws, new_holes = self.detect_screws_and_holes(new_screen)
                    
                    # Verification via Disappearance: If 's' is gone, the move was valid!
                    if not self.is_screw_still_there(s, new_screws):
                        print("=> SUCCESS: Screw moved! Board state changed.")
                        moved = True
                        break
                    else:
                        print("=> FAILED: Screw didn't move (blocked or invalid move).")
                        
                if moved:
                    # Break out of the loops to start scanning the fresh new state
                    break
                    
            if not moved:
                print("Exhausted all combinations but no moves were successful. Deadlocked!")
                # Same here, might need logic to click the restart button for the level.
                break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Valor Legends Screw Bot")
    parser.add_argument("--debug-actions", action="store_true", help="Save before and after screenshots for every action")
    args = parser.parse_args()
    
    bot = ScrewBot(DeviceController(), debug_actions=args.debug_actions)
    bot.run()
