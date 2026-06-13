from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import cv2
import numpy as np

from src.vision_matcher import read_image, write_image


@dataclass(frozen=True)
class CropBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


def find_blue_boxes(image: np.ndarray) -> List[CropBox]:
    """Detect Paint-style blue outline rectangles in a screenshot."""
    mask = _blue_outline_mask(image)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    img_h, img_w = image.shape[:2]
    boxes: List[CropBox] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if w < 20 or h < 12:
            continue
        if area < 300 or area > img_w * img_h * 0.9:
            continue

        roi_mask = mask[y : y + h, x : x + w]
        fill_ratio = float(np.count_nonzero(roi_mask)) / float(area)
        if fill_ratio > 0.55:
            continue

        band = max(2, min(6, min(w, h) // 8))
        top = np.count_nonzero(roi_mask[:band, :]) / float(band * w)
        bottom = np.count_nonzero(roi_mask[-band:, :]) / float(band * w)
        left = np.count_nonzero(roi_mask[:, :band]) / float(band * h)
        right = np.count_nonzero(roi_mask[:, -band:]) / float(band * h)
        if min(top, bottom, left, right) < 0.35:
            continue

        boxes.append(CropBox(x, y, w, h))

    return _dedupe_boxes(sorted(boxes, key=lambda box: (box.y, box.x)))


def crop_inside_blue_box(image: np.ndarray, box: CropBox) -> np.ndarray:
    roi = image[box.y : box.y + box.height, box.x : box.x + box.width]
    mask = _blue_outline_mask(roi)

    y_min, y_max = 0, box.height - 1
    x_min, x_max = 0, box.width - 1
    mid_x1, mid_x2 = int(box.width * 0.25), max(int(box.width * 0.75), int(box.width * 0.25) + 1)
    mid_y1, mid_y2 = int(box.height * 0.25), max(int(box.height * 0.75), int(box.height * 0.25) + 1)

    while y_min < y_max and np.count_nonzero(mask[y_min, mid_x1:mid_x2]) > 0:
        y_min += 1
    while y_max > y_min and np.count_nonzero(mask[y_max, mid_x1:mid_x2]) > 0:
        y_max -= 1
    while x_min < x_max and np.count_nonzero(mask[mid_y1:mid_y2, x_min]) > 0:
        x_min += 1
    while x_max > x_min and np.count_nonzero(mask[mid_y1:mid_y2, x_max]) > 0:
        x_max -= 1

    y_min = min(y_min + 1, y_max)
    y_max = max(y_max - 1, y_min)
    x_min = min(x_min + 1, x_max)
    x_max = max(x_max - 1, x_min)
    return roi[y_min : y_max + 1, x_min : x_max + 1]


def _blue_outline_mask(image: np.ndarray) -> np.ndarray:
    """Mask the dark blue/primary blue strokes Paint uses for manual crop boxes."""
    blue, green, red = cv2.split(image)
    strongest_other = np.maximum(red, green).astype(np.int16)
    blue_i = blue.astype(np.int16)
    mask = (
        (blue >= 145)
        & (red <= 120)
        & (green <= 125)
        & ((blue_i - strongest_other) >= 55)
    )
    return mask.astype(np.uint8) * 255


def run_paint_crop_workflow(
    screenshot_path: Path,
    *,
    output_dir: Optional[Path] = None,
    input_func: Callable[[str], str] = input,
    paint_runner: Optional[Callable[[Path], None]] = None,
) -> List[Path]:
    if output_dir is None:
        output_dir = screenshot_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    runner = paint_runner or open_mspaint_blocking

    print(f"Open Paint and draw blue outline boxes: {screenshot_path}", flush=True)
    print("After drawing boxes, press Ctrl+S, close Paint, then this tool will crop them.", flush=True)
    runner(screenshot_path)

    image = read_image(screenshot_path, cv2.IMREAD_COLOR)
    boxes = find_blue_boxes(image)
    if not boxes:
        print("No blue boxes found. Keep the screenshot for review.", flush=True)
        return []

    print(f"Detected {len(boxes)} blue box(es).", flush=True)
    saved: List[Path] = []
    for index, box in enumerate(boxes, start=1):
        crop = crop_inside_blue_box(image, box)
        if crop.size == 0:
            print(f"Crop {index}: empty crop, skipped.", flush=True)
            continue

        preview_path = output_dir / f"crop_{index:02d}_preview.png"
        write_image(preview_path, crop)
        print(f"Crop {index}: opening preview in Paint: {preview_path}", flush=True)
        runner(preview_path)

        raw_name = input_func(f"Filename for crop {index} (blank to skip, no .png needed): ").strip()
        if not raw_name:
            print(f"Crop {index}: skipped.", flush=True)
            continue

        dest_path = _unique_path(output_dir / f"{_safe_filename(raw_name)}.png")
        shutil.copy2(preview_path, dest_path)
        print(f"Saved: {dest_path}", flush=True)
        saved.append(dest_path)

    return saved


def open_mspaint_blocking(path: Path) -> None:
    subprocess.run(["mspaint", str(path)], check=False)


def _dedupe_boxes(boxes: Iterable[CropBox]) -> List[CropBox]:
    kept: List[CropBox] = []
    for box in boxes:
        duplicate = False
        for existing in kept:
            if _intersection_over_union(box, existing) > 0.82:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def _intersection_over_union(a: CropBox, b: CropBox) -> float:
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.width, b.x + b.width)
    y2 = min(a.y + a.height, b.y + b.height)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = a.area + b.area - inter
    return inter / float(union)


def _safe_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    if not safe:
        safe = f"crop_{time.strftime('%Y%m%d_%H%M%S')}"
    return safe


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
