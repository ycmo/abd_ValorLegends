import cv2
import numpy as np
import hashlib

def get_hash_map():
    return {
        '7507d180': '1', 'a562d68e': '1', 'd9e1978c': '1',
        '8bfdef99': '2', 'cddb6d11': '2',
        '22fa0bf5': '3',
        '2cd0bbff': '4', '7ad3e45a': '4', '5d33125e': '4',
        '4e0994ce': '5', 'c6fb5fbc': '5', '102414d0': '5',
        '0514a874': '6',
        '65578314': '7', 'fcfbd7a3': '7', '98e8090e': '7',
        '820bef7d': '0', '1144e936': '0',
        'bb30d0aa': '8',
        'a216091f': 'k', '9c4c9831': 'k',
    }

def extract_arena_powers(screen):
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    
    hash_map = get_hash_map()
    results = []
    
    # 4 rows, 2 columns grid
    y_centers = [146, 224, 302, 380]
    x_starts = [200, 575]
    
    for row_idx, y_center in enumerate(y_centers):
        for col_idx, x_start in enumerate(x_starts):
            row_img = thresh[y_center-20:y_center+20, x_start:x_start+150]
            contours, _ = cv2.findContours(row_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            char_boxes = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if 4 < w < 25 and 8 < h < 25:
                    char_boxes.append((x, y, w, h))
                    
            char_boxes.sort(key=lambda b: b[0])
            
            line = ""
            for (x, y, w, h) in char_boxes:
                char_img = row_img[y:y+h, x:x+w]
                h_str = hashlib.md5(char_img.tobytes()).hexdigest()[:8]
                if h_str in hash_map:
                    line += hash_map[h_str]
            
            if line.endswith('k1'):
                line = line[:-1]
                
            results.append({
                'row': row_idx + 1,
                'col': col_idx + 1,
                'power_str': line,
                'power_val': int(line.replace('k', '')) if 'k' in line and line.replace('k', '').isdigit() else -1
            })
            
    return results

if __name__ == "__main__":
    img_path = "scratch/live_arena_8.png"
    img = cv2.imdecode(np.frombuffer(open(img_path, "rb").read(), dtype=np.uint8), cv2.IMREAD_COLOR)
    results = extract_arena_powers(img)
    for r in results:
        print(f"Col {r['col']}, Row {r['row']}: {r['power_str']}")
