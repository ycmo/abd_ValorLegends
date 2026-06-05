from __future__ import annotations

import hashlib
import re
from typing import Dict, List

import cv2
import numpy as np


def parse_power_value(text: str) -> int:
    cleaned = text.lower().replace(",", "").replace(" ", "")
    match = re.search(r"(\d+)(k)?", cleaned)
    if not match:
        return -1
    value = int(match.group(1))
    return value if match.group(2) == "k" else value // 1000


def get_arena_hash_map() -> Dict[str, str]:
    return {
        "7507d180": "1",
        "a562d68e": "1",
        "d9e1978c": "1",
        "8bfdef99": "2",
        "cddb6d11": "2",
        "22fa0bf5": "3",
        "2cd0bbff": "4",
        "7ad3e45a": "4",
        "5d33125e": "4",
        "4e0994ce": "5",
        "c6fb5fbc": "5",
        "102414d0": "5",
        "0514a874": "6",
        "65578314": "7",
        "fcfbd7a3": "7",
        "98e8090e": "7",
        "820bef7d": "0",
        "1144e936": "0",
        "bb30d0aa": "8",
        "a216091f": "k",
        "9c4c9831": "k",
    }


def extract_arena_powers_hash(screen: np.ndarray) -> List[dict]:
    """Fast hash OCR for the current 960x540 arena opponent layout."""

    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    hash_map = get_arena_hash_map()
    results = []

    y_centers = [146, 224, 302, 380]
    x_starts = [200, 575]

    for row_idx, y_center in enumerate(y_centers):
        for col_idx, x_start in enumerate(x_starts):
            row_img = thresh[y_center - 20 : y_center + 20, x_start : x_start + 150]
            contours, _ = cv2.findContours(row_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if 4 < w < 25 and 8 < h < 25:
                    boxes.append((x, y, w, h))
            boxes.sort(key=lambda box: box[0])

            text = ""
            for x, y, w, h in boxes:
                char_img = row_img[y : y + h, x : x + w]
                key = hashlib.md5(char_img.tobytes()).hexdigest()[:8]
                text += hash_map.get(key, "")

            if text.endswith("k1"):
                text = text[:-1]

            results.append(
                {
                    "row": row_idx + 1,
                    "col": col_idx + 1,
                    "power_text": text,
                    "power_k": parse_power_value(text),
                }
            )
    return results

