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


ARENA_POWER_COL_X_RANGES = ((200, 350), (580, 730))
ARENA_POWER_ROW_Y_RANGES = ((140, 180), (218, 258), (296, 336), (374, 414))


def build_easyocr_reader():
    import easyocr

    return easyocr.Reader(["en"], gpu=False, verbose=False)


def extract_arena_powers_easyocr(screen: np.ndarray, reader=None) -> List[dict]:
    """Read the 8 fixed-position Arena opponent power values with EasyOCR.

    The ROI intentionally includes only the power text area. EasyOCR sometimes
    also sees score text farther right, so boxes near the far-right edge are
    ignored before combining text fragments.
    """

    if reader is None:
        reader = build_easyocr_reader()

    results = []
    for row_idx, (y0, y1) in enumerate(ARENA_POWER_ROW_Y_RANGES):
        for col_idx, (x0, x1) in enumerate(ARENA_POWER_COL_X_RANGES):
            roi = screen[y0:y1, x0:x1]
            roi_large = cv2.resize(roi, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            roi_pad = cv2.copyMakeBorder(
                roi_large,
                20,
                20,
                20,
                20,
                cv2.BORDER_CONSTANT,
                value=[255, 255, 255],
            )
            ocr_results = reader.readtext(roi_pad, allowlist="0123456789kK,")
            text, confidence = _combine_arena_power_ocr_results(ocr_results)
            results.append(
                {
                    "row": row_idx + 1,
                    "col": col_idx + 1,
                    "power_text": text,
                    "power_k": parse_power_value(text),
                    "confidence": confidence,
                }
            )
    return results


def _combine_arena_power_ocr_results(ocr_results) -> tuple[str, float]:
    pieces = []
    for box, text, confidence in ocr_results:
        clean = str(text).lower().replace(" ", "")
        if not any(char.isdigit() for char in clean):
            continue
        xs = _box_x_values(box)
        if not xs:
            continue
        left = min(xs)
        center = sum(xs) / len(xs)
        if center > 240:
            continue
        pieces.append((left, clean, float(confidence)))

    if not pieces:
        return "", 0.0

    pieces.sort(key=lambda item: item[0])
    text = "".join(piece[1] for piece in pieces)
    if "k" in text:
        text = text[: text.index("k") + 1]
    confidence = min(piece[2] for piece in pieces)
    return text, confidence


def _box_x_values(box) -> List[float]:
    values = []
    for point in box:
        try:
            values.append(float(point[0]))
        except (TypeError, ValueError, IndexError):
            continue
    return values
