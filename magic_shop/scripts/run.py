import time
import os
import sys
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher, write_image
from src.ocr_utils import read_texts_easyocr, build_easyocr_reader
from src.config import DEFAULT_SERIAL

def get_gold_amount(device, debug_dir, reader, debug=False):
    img = device.screenshot()
    gold_img = img[15:45, 715:820]
    gold_path = os.path.join(debug_dir, "gold_crop.png")
    write_image(Path(gold_path), gold_img)
    
    results = read_texts_easyocr(gold_img, reader=reader)
    if not results:
        if debug:
            print("[DEBUG] OCR returned no results for gold.")
        return 0
        
    text = results[0]["text"]
    if debug:
        print(f"[DEBUG] Raw gold OCR text: '{text}'")
    text = text.replace('k', '').replace('K', '').replace(',', '').replace('.', '').strip()
    try:
        val = int(text)
        if debug:
            print(f"[DEBUG] Parsed gold amount: {val}")
        return val
    except ValueError:
        if debug:
            print(f"[DEBUG] Failed to parse gold amount: {text}")
        return 0

import cv2
import numpy as np

def buy_visible_items(device, matcher, item_templates, debug_dir, gold_coin_path, debug=False):
    bought_something_total = False
    confirm_btn_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'buy_confirm_btn.png')
    attempted = set()
    
    while True:
        img = device.screenshot()
        bought_in_this_iteration = False
        
        for item_name, template_path in item_templates.items():
            template_raw = read_image(Path(template_path), cv2.IMREAD_UNCHANGED)
            template, mask = matcher._split_template_and_mask(template_raw)
            haystack = img
            
            if mask is not None:
                result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED, mask=mask)
                result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
            else:
                result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
                
            threshold = 0.85
            locations = np.where(result >= threshold)
            
            # locations is a tuple of (y_array, x_array). Zip them into a list of points.
            points = list(zip(*locations[::-1]))
            
            # Sort points by score descending or just process them. Let's process them.
            # We want to skip points that are too close to each other (non-maximum suppression)
            filtered_points = []
            for pt in points:
                # pt is (x, y) which is the top-left of the match.
                # Center is x + tw//2, y + th//2
                tw, th = template.shape[1], template.shape[0]
                cx, cy = pt[0] + tw // 2, pt[1] + th // 2
                
                # Check if it's close to an already filtered point
                too_close = False
                for fp in filtered_points:
                    if abs(cx - fp[0]) < 20 and abs(cy - fp[1]) < 20:
                        too_close = True
                        break
                if not too_close:
                    filtered_points.append((cx, cy))
            
            for cx, cy in filtered_points:
                x, y = cx, cy
                pos_key = (x // 20, y // 20)
                if pos_key in attempted:
                    continue
                
                if y < 110 or y > 500:
                    if debug:
                        print(f"[DEBUG] Found {item_name} at {x}, {y} but near edge. Skipping.")
                    attempted.add(pos_key)
                    continue
                
                # Check if it costs gold
                price_roi = img[y+50:y+120, max(0, x-50):min(img.shape[1], x+50)]
                coin_match = matcher.match_template(price_roi, Path(gold_coin_path), threshold=0.7)
                if not coin_match:
                    if debug:
                        print(f"[DEBUG] Found {item_name} at {x}, {y} but no gold coin found in price button. Skipping.")
                    attempted.add(pos_key)
                    continue
                
                attempted.add(pos_key)
                price_x = x
                price_y = y + 85
                print(f"Found {item_name} at {x}, {y}. Tapping price button at {price_x}, {price_y}")
                
                if debug:
                    timestamp = int(time.time() * 1000)
                    debug_path = os.path.join(debug_dir, f"debug_pretap_{timestamp}.png")
                    write_image(Path(debug_path), img)
                    print(f"[DEBUG] Pre-tap screenshot saved to {debug_path}")
                    print(f"[DEBUG] Recognized item: {item_name} at ({x}, {y}) costing gold")
                
                device.tap(price_x, price_y)
                time.sleep(1.5)
                
                confirm_img = device.screenshot()
                confirm_match = matcher.match_template(confirm_img, Path(confirm_btn_path), threshold=0.8)
                if confirm_match:
                    btn_x, btn_y = confirm_match.center
                    print(f"Tapping buy confirm button at {btn_x}, {btn_y}")
                    
                    if debug:
                        timestamp = int(time.time() * 1000)
                        debug_path = os.path.join(debug_dir, f"debug_preconfirm_{timestamp}.png")
                        write_image(Path(debug_path), confirm_img)
                        print(f"[DEBUG] Pre-confirm screenshot saved to {debug_path}")
                        print(f"[DEBUG] Recognized confirm button at ({btn_x}, {btn_y})")
                    
                    device.tap(btn_x, btn_y)
                    time.sleep(1.5)
                    bought_in_this_iteration = True
                    bought_something_total = True
                    
                    device.tap(50, 50)
                    time.sleep(0.5)
                else:
                    print("No buy confirm button found, might be sold out or error.")
                    device.tap(50, 50)
                    time.sleep(1)
                
                break # Break inner loop to take a fresh screenshot
                
            if bought_in_this_iteration:
                break # Also break outer for loop to take a fresh screenshot
                
        if not bought_in_this_iteration:
            break
            
    return bought_something_total

def main():
    parser = argparse.ArgumentParser(description='Magic Shop Automation')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode to save screenshots and print detailed info')
    args = parser.parse_args()
    
    print("Starting Magic Shop automation...")
    device = DeviceController(DEFAULT_SERIAL)
    matcher = VisionMatcher()
    reader = build_easyocr_reader()
    
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    assets_dir = os.path.join(base_dir, 'assets')
    debug_dir = os.path.join(base_dir, 'debug_output')
    os.makedirs(debug_dir, exist_ok=True)
    
    item_templates = {
        '紫珠': os.path.join(assets_dir, 'item_purple_bead.png'),
        '金牌': os.path.join(assets_dir, 'item_gold_medal.png'),
        '競技場票': os.path.join(assets_dir, 'item_arena_ticket.png'),
        '英雄碎片': os.path.join(assets_dir, 'item_hero_shard.png'),
    }
    
    gold_coin_path = os.path.join(assets_dir, 'gold_coin.png')
    refresh_100_path = os.path.join(assets_dir, 'refresh_100.png')
    
    while True:
        print("Scanning top items...")
        buy_visible_items(device, matcher, item_templates, debug_dir, gold_coin_path, debug=args.debug)
        
        print("Scrolling down...")
        if args.debug:
            timestamp = int(time.time() * 1000)
            debug_path = os.path.join(debug_dir, f"debug_preswipe_down_{timestamp}.png")
            img = device.screenshot()
            write_image(Path(debug_path), img)
            print(f"[DEBUG] Pre-swipe (down) screenshot saved to {debug_path}")
            
        device.swipe(480, 450, 480, 150, duration_ms=500)
        time.sleep(2)
        
        print("Scanning bottom items...")
        buy_visible_items(device, matcher, item_templates, debug_dir, gold_coin_path, debug=args.debug)
        
        print("Scrolling back to top...")
        if args.debug:
            timestamp = int(time.time() * 1000)
            debug_path = os.path.join(debug_dir, f"debug_preswipe_up_{timestamp}.png")
            img = device.screenshot()
            write_image(Path(debug_path), img)
            print(f"[DEBUG] Pre-swipe (up) screenshot saved to {debug_path}")
            
        device.swipe(480, 150, 480, 450, duration_ms=500)
        time.sleep(2)
        
        gold = get_gold_amount(device, debug_dir, reader, debug=args.debug)
        print(f"Current gold: {gold}k")
        if gold < 13000:
            print("Gold is less than 13000k. Stopping refresh.")
            break
            
        img = device.screenshot()
        refresh_match = matcher.match_template(img, Path(refresh_100_path), threshold=0.85)
        if not refresh_match:
            print("Refresh button is not 100 gems (or not found). Stopping.")
            break
            
        print("Conditions met. Refreshing shop...")
        if args.debug:
            timestamp = int(time.time() * 1000)
            debug_path = os.path.join(debug_dir, f"debug_prerefresh_{timestamp}.png")
            write_image(Path(debug_path), img)
            print(f"[DEBUG] Pre-refresh screenshot saved to {debug_path}")
            
        rx, ry = refresh_match.center
        device.tap(rx, ry)
        time.sleep(2)
        
    print("Exiting Magic Shop...")
    device.tap(45, 30)
    time.sleep(1)
    print("Automation complete.")

if __name__ == "__main__":
    main()
