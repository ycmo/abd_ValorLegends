import os
from adb_client import get_devices, take_screenshot, tap_coordinate, run_adb_cmd
from vision import find_template

def list_devices_action() -> None:
    """
    Retrieves and prints the list of connected ADB devices.
    """
    devices_info = get_devices()
    print(devices_info)

def screenshot_action(output_path: str = "screenshots/current.png") -> None:
    """
    Takes a screenshot, saves it to output_path, and prints metadata.
    """
    width, height, byte_size = take_screenshot(output_path)
    # Print exactly as required:
    # 2. screenshot 產生 screenshots/current.png，並印出圖片尺寸、byte size、路徑。
    print(f"Screenshot Path: {os.path.abspath(output_path)}")
    print(f"Dimensions: {width}x{height}")
    print(f"Byte Size: {byte_size} bytes")

def tap_action(x: int, y: int) -> None:
    """
    Taps coordinates (x, y) and prints the result.
    """
    tap_coordinate(x, y)
    # 3. tap 使用 adb shell input tap x y，成功時印出座標。
    print(f"Tapped coordinates: ({x}, {y})")

def find_action(template_path: str, image_path: str = "screenshots/current.png") -> None:
    """
    Finds a template image inside a base image. If the base image is the default and does
    not exist, takes a screenshot first.
    Prints coordinates and confidence.
    """
    if not os.path.exists(image_path) and image_path == "screenshots/current.png":
        # Automatically take a screenshot if base image is missing
        screenshot_action(image_path)
        
    (cx, cy), confidence = find_template(image_path, template_path)
    # 4. find 使用 OpenCV template matching，回傳座標與 confidence。
    print(f"Found template {template_path} at: ({cx}, {cy})")
    print(f"Confidence: {confidence:.6f}")

def print_results_table(results) -> None:
    print("\n| index | before screenshot | tapped coordinate | after screenshot | returned to daily task | notes |")
    print("|---|---|---|---|---|---|")
    for r in results:
        print(f"| {r['index']} | {r['before']} | {r['coord']} | {r['after']} | {r['returned']} | {r['notes']} |")

class HumanReviewRequired(Exception):
    """
    Exception raised when automation encounters an ambiguous situation requiring human review.
    """
    pass

def request_human_review(reason: str, current_task: str = "Unknown", attempted_returns: str = "None") -> None:
    import time
    import os
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"screenshots/manual_review_{timestamp}.png"
    try:
        take_screenshot(screenshot_path)
    except Exception as e:
        print(f"Error capturing review screenshot: {e}")
        screenshot_path = "current.png (Failed to take screenshot)"
        
    print("\n" + "!"*60)
    print("STOPPED_FOR_HUMAN_REVIEW")
    print(f"Reason: {reason}")
    print(f"Current Screenshot Path: {os.path.abspath(screenshot_path)}")
    print(f"Current Attempted Task / Action: {current_task}")
    print(f"Attempted Return Strategies: {attempted_returns}")
    print("Please review the screen and confirm the next steps manually.")
    print("!"*60 + "\n")
    raise HumanReviewRequired(reason)

def probe_daily_tasks_action() -> None:
    if not os.path.exists("assets/daily_tasks_title.png"):
        raise FileNotFoundError("daily_tasks_title.png template not found in assets/ directory.")
    if not os.path.exists("assets/go_button.png"):
        raise FileNotFoundError("go_button.png template not found in assets/ directory.")
    if not os.path.exists("assets/task_button.png"):
        raise FileNotFoundError("task_button.png template not found in assets/ directory.")
        
    print("Starting full probe-daily-tasks...")
    results = []
    tapped_task_crops = []
    
    # Load status graph configuration
    import json
    status_graph = {}
    status_graph_path = "data/status_graph.json"
    if os.path.exists(status_graph_path):
        try:
            with open(status_graph_path, "r", encoding="utf-8") as f:
                status_graph = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load status_graph.json: {e}")

    def get_wait_seconds_for_tap(x: int, y: int) -> tuple[str, float, str]:
        fallback_wait = 4.5
        target_node = "unknown"
        for edge in status_graph.get("edges", []):
            if edge.get("from_node") == "daily_tasks" and edge.get("coordinate"):
                coord = edge["coordinate"]
                if abs(coord.get("x", 0) - x) <= 15 and abs(coord.get("y", 0) - y) <= 15:
                    target_node = edge.get("to_node", "unknown")
                    break
        if target_node != "unknown":
            for node in status_graph.get("nodes", []):
                if node.get("node_id") == target_node:
                    wait_sec = node.get("wait_seconds")
                    if wait_sec is not None:
                        return target_node, float(wait_sec), "status_graph.json"
        return target_node, fallback_wait, "fallback"
    
    def check_on_daily_tasks() -> bool:
        temp_chk = "screenshots/temp_check.png"
        try:
            take_screenshot(temp_chk)
            _, confidence = find_template(temp_chk, "assets/daily_tasks_title.png")
            if os.path.exists(temp_chk):
                os.remove(temp_chk)
            
            # Grey zone template confidence warning trigger
            if 0.6 <= confidence < 0.85:
                request_human_review(
                    reason=f"Daily Tasks page title match confidence is in a gray zone ({confidence:.4f}).",
                    current_task="Verify Daily Tasks page",
                    attempted_returns="None"
                )
                
            return confidence >= 0.85
        except HumanReviewRequired:
            raise
        except Exception:
            return False

    def try_return_to_daily_tasks() -> bool:
        if check_on_daily_tasks():
            return True
            
        import time
        
        # We try 3 cycles of recovery
        for cycle in range(3):
            # Press back key
            print(f"Cycle {cycle+1}: Sending Android back keyevent 4...")
            run_adb_cmd(["shell", "input", "keyevent", "4"])
            time.sleep(3.0)
            if check_on_daily_tasks():
                return True
                
            # Tap 否 (385, 745) to close quit dialog if it popped up
            print("Tapping 否 (385, 745) to dismiss quit game dialog if open...")
            tap_coordinate(385, 745)
            time.sleep(1.5)
            
            # Tap 掛機 (800, 840) to switch to campaign main page
            print("Tapping 掛機 tab (800, 840)...")
            tap_coordinate(800, 840)
            time.sleep(2.0)
            
            # Tap 任務 (1555, 100) to open Daily Tasks page
            print("Tapping 任務 button (1555, 100)...")
            tap_coordinate(1555, 100)
            time.sleep(3.0)
            if check_on_daily_tasks():
                return True
                
        # Last resort fallback: tap top-left back (50, 50)
        print("Still not in daily tasks page. Trying top-left back button area (50, 50)...")
        tap_coordinate(50, 50)
        time.sleep(3.0)
        if check_on_daily_tasks():
            return True
            
        # Tap 掛機 (800, 840) and 任務 (1555, 100)
        tap_coordinate(800, 840)
        time.sleep(2.0)
        tap_coordinate(1555, 100)
        time.sleep(3.0)
        if check_on_daily_tasks():
            return True
            
        return False

    def is_duplicate_task(current_crop, threshold=0.92) -> bool:
        import cv2
        for crop in tapped_task_crops:
            if current_crop.shape == crop.shape:
                res = cv2.matchTemplate(current_crop, crop, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                
                # Gray zone deduplication confidence warning trigger
                if 0.85 <= max_val < threshold:
                    request_human_review(
                        reason=f"Task deduplication confidence is in a gray zone (max similarity: {max_val:.4f}). Unsure if duplicate.",
                        current_task="Task duplicate check",
                        attempted_returns="None"
                    )
                    
                if max_val >= threshold:
                    return True
        return False

    if not check_on_daily_tasks():
        request_human_review(
            reason="Not starting on the Daily Tasks page. Make sure the Daily Tasks page is open.",
            current_task="Start check",
            attempted_returns="None"
        )

    # Loop pages and scroll
    import cv2
    import numpy as np
    import time
    
    idx = 1
    page_num = 1
    
    template = cv2.imread("assets/go_button.png")
    h, w = template.shape[:2]
    
    while True:
        print(f"\n=================== Scanning Page {page_num} ===================")
        current_shot = f"screenshots/page_scan_{page_num}.png"
        screenshot_action(current_shot)
        
        img = cv2.imread(current_shot)
        if img is None:
            print(f"Error reading {current_shot}")
            break
            
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= 0.85)
        
        points = sorted(list(zip(*loc[::-1])), key=lambda p: p[1])
        grouped_buttons = []
        for p in points:
            # Filter buttons that are vertically within the task list area
            if (150 <= p[1] <= 880) and not any(abs(g[1] - p[1]) < 20 and abs(g[0] - p[0]) < 20 for g in grouped_buttons):
                grouped_buttons.append(p)
                
        print(f"Detected {len(grouped_buttons)} active 'Go' buttons on Page {page_num}.")
        
        # Trigger review if first page has 0 detected buttons
        if page_num == 1 and len(grouped_buttons) == 0:
            request_human_review(
                reason="No active 'Go' buttons detected on the first page of Daily Tasks.",
                current_task="Scan Page 1",
                attempted_returns="None"
            )
            
        # Process each button on this page
        for i in range(len(grouped_buttons)):
            print(f"\n--- Page {page_num}, Button Item {i+1}/{len(grouped_buttons)} (Global Index {idx}) ---")
            
            before_shot = f"screenshots/probe_{idx:03d}_before.png"
            screenshot_action(before_shot)
            
            img_current = cv2.imread(before_shot)
            res_current = cv2.matchTemplate(img_current, template, cv2.TM_CCOEFF_NORMED)
            loc_current = np.where(res_current >= 0.85)
            points_current = sorted(list(zip(*loc_current[::-1])), key=lambda p: p[1])
            
            # Apply same task list area filter
            grouped_current = []
            for p in points_current:
                if (150 <= p[1] <= 880) and not any(abs(g[1] - p[1]) < 20 and abs(g[0] - p[0]) < 20 for g in grouped_current):
                    grouped_current.append(p)
                    
            if i >= len(grouped_current):
                print(f"Warning: Index {i} out of range for current page buttons. Tapping original coordinates.")
                orig_p = grouped_buttons[i]
                target_x = orig_p[0] + w // 2
                target_y = orig_p[1] + h // 2
            else:
                p = grouped_current[i]
                target_x = p[0] + w // 2
                target_y = p[1] + h // 2
                
            # Crop the task text label to check for duplicates
            task_crop = img_current[target_y-35:target_y+35, 220:650]
            if is_duplicate_task(task_crop):
                print(f"Skipping duplicate task detected at coordinate ({target_x}, {target_y}).")
                continue
                
            # Save to tapped tasks
            tapped_task_crops.append(task_crop)
            
            # Save unique task label for identification later
            os.makedirs("screenshots/task_labels", exist_ok=True)
            cv2.imwrite(f"screenshots/task_labels/task_{idx:03d}_label.png", task_crop)
            
            print(f"Action: Tapping 'Go' button at ({target_x}, {target_y})")
            tap_coordinate(target_x, target_y)
            
            t_node, w_seconds, src = get_wait_seconds_for_tap(target_x, target_y)
            print(f"target_node={t_node}")
            print(f"wait_seconds={w_seconds}")
            print(f"source={src}")
            time.sleep(w_seconds)
            
            after_shot = f"screenshots/probe_{idx:03d}_after.png"
            screenshot_action(after_shot)
            
            # Return to daily tasks page
            returned = try_return_to_daily_tasks()
            
            if not returned:
                request_human_review(
                    reason="Failed to return to Daily Tasks page using recovery strategies.",
                    current_task=f"Return after task index {idx} (Go tapped at {target_x}, {target_y})",
                    attempted_returns="1. Send Back Keyevent 4; 2. Tap 否 (385, 745); 3. Tap 掛機 (800, 840); 4. Tap 任務 (1555, 100); 5. Tap (50, 50)"
                )
                
            results.append({
                "index": idx,
                "before": before_shot,
                "coord": f"({target_x}, {target_y})",
                "after": after_shot,
                "returned": returned,
                "notes": "Success"
            })
            idx += 1
            
        # Try to scroll down to reveal more tasks
        print(f"\n--- Scroll check after Page {page_num} ---")
        scroll_success = False
        
        for attempt in range(1, 4):
            scroll_before = f"screenshots/scroll_p{page_num}_{attempt}_before.png"
            screenshot_action(scroll_before)
            
            print("Swiping up from y=780 to y=320 in the middle area...")
            run_adb_cmd(["shell", "input", "swipe", "900", "780", "900", "320", "900"])
            time.sleep(3.0)
            
            scroll_after = f"screenshots/scroll_p{page_num}_{attempt}_after.png"
            screenshot_action(scroll_after)
            
            img_b = cv2.imread(scroll_before)
            img_a = cv2.imread(scroll_after)
            if img_b is not None and img_a is not None:
                crop_b = img_b[350:880, 150:1500]
                crop_a = img_a[350:880, 150:1500]
                if crop_b.shape == crop_a.shape:
                    diff = cv2.absdiff(crop_b, crop_a)
                    mean_diff = float(np.mean(diff))
                    print(f"Scroll attempt {attempt}: mean pixel difference = {mean_diff:.4f}")
                    if mean_diff >= 5.0:
                        scroll_success = True
                        print("Scroll succeeded!")
                        break
                    else:
                        print("Scroll did not change the screen.")
            else:
                print("Could not read scroll screenshots.")
                
        if not scroll_success:
            print("No more scrollable content. Stopping exploration.")
            break
            
        page_num += 1
        
    print("\n--- Completed full daily tasks probe exploration! ---")
    print_results_table(results)


def run_small_tasks_action(tasks: list) -> None:
    import time
    import os
    from adb_client import run_adb_cmd, take_screenshot, tap_coordinate
    from vision import find_template

    print(f"Starting run-small-tasks trial for tasks: {tasks}")
    
    daily_tasks_title = "assets/daily_tasks_title.png"
    task_button = "assets/task_button.png"
    
    for task in tasks:
        if task == "endless_trial":
            print("\n--- [Task: Endless Trial] ---")
            # Step 1: Ensure we are on Daily Tasks page
            temp_shot = "screenshots/run_temp.png"
            take_screenshot(temp_shot)
            _, conf = find_template(temp_shot, daily_tasks_title)
            if os.path.exists(temp_shot):
                os.remove(temp_shot)
                
            if conf < 0.85:
                # If not on daily tasks, open it from lobby if lobby tasks button is visible
                take_screenshot(temp_shot)
                _, lobby_conf = find_template(temp_shot, task_button)
                if os.path.exists(temp_shot):
                    os.remove(temp_shot)
                if lobby_conf >= 0.85:
                    print("Tapping Tasks button (1555, 100) to open Daily Tasks page...")
                    tap_coordinate(1555, 100)
                    time.sleep(3.0)
                else:
                    request_human_review("Not starting on Daily Tasks page and cannot locate Tasks button to navigate.", "Endless Trial Start", "None")

            # Step 2: Go to Endless Trial from Daily Tasks
            print("Tapping Endless Trial Go button at (1399, 414)...")
            tap_coordinate(1399, 414)
            time.sleep(4.5)
            
            # Step 3: Enter the first portal card
            print("Tapping first portal (1100, 507)...")
            tap_coordinate(1100, 507)
            time.sleep(3.0)
            
            # Step 4: Click the Challenge button inside portal detail screen
            print("Tapping Challenge button (799, 819)...")
            tap_coordinate(799, 819)
            print("Waiting 25 seconds for battle to complete...")
            time.sleep(25.0)
            
            # Step 5: Dismiss Victory/Defeat screen and battle stats overlays (requires 2 taps)
            print("Tapping screen center (800, 450) to dismiss Victory/Defeat logo...")
            tap_coordinate(800, 450)
            time.sleep(3.5)
            print("Tapping screen center (800, 450) to dismiss battle rewards/stats overview...")
            tap_coordinate(800, 450)
            time.sleep(3.5)
            
            # Step 6: Return back to Daily Tasks page (using verify-and-retry loop)
            returned = False
            for attempt in range(3):
                print(f"Tapping Golden back button area (50, 60), attempt {attempt+1}...")
                tap_coordinate(50, 60)
                time.sleep(3.0)
                
                temp_shot = "screenshots/run_temp.png"
                take_screenshot(temp_shot)
                _, conf = find_template(temp_shot, daily_tasks_title)
                if os.path.exists(temp_shot):
                    os.remove(temp_shot)
                if conf >= 0.85:
                    returned = True
                    break
            if not returned:
                request_human_review("Failed to return to Daily Tasks page after 3 back button taps.", "Endless Trial Return", "None")
            print("Endless Trial task completed successfully!")
            
        elif task == "campaign":
            print("\n--- [Task: Campaign] ---")
            # Step 1: Navigate to Campaign main page
            print("Tapping 掛機 tab (800, 840) to ensure Campaign lobby screen...")
            tap_coordinate(800, 840)
            time.sleep(3.0)
            
            # Step 2: Click the lobby challenge button
            print("Tapping Campaign lobby challenge button at (1387, 712)...")
            tap_coordinate(1387, 712)
            time.sleep(4.0)
            
            # Step 3: Click the Start Battle button on preparation screen
            print("Tapping Start Battle button at (1167, 790)...")
            tap_coordinate(1167, 790)
            print("Waiting 25 seconds for battle to complete...")
            time.sleep(25.0)
            
            # Step 4: Dismiss Victory/Defeat screen and battle stats overlays (requires 2 taps)
            print("Tapping screen center (800, 450) to dismiss Victory/Defeat logo...")
            tap_coordinate(800, 450)
            time.sleep(3.5)
            print("Tapping screen center (800, 450) to dismiss battle rewards/stats overview...")
            tap_coordinate(800, 450)
            time.sleep(3.5)
            print("Campaign task completed successfully!")

