from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Literal, Optional, Sequence

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


BoxColor = Literal["blue", "red", "green"]


def find_blue_boxes(image: np.ndarray) -> List[CropBox]:
    """Detect Paint-style blue outline rectangles in a screenshot."""
    return find_colored_boxes(image, "blue")


def find_red_boxes(image: np.ndarray) -> List[CropBox]:
    """Detect Paint-style red outline rectangles used for tap/click regions."""
    return find_colored_boxes(image, "red")


def find_green_boxes(image: np.ndarray) -> List[CropBox]:
    """Detect Paint-style green outline rectangles used for recognition anchors."""
    return find_colored_boxes(image, "green")


def find_colored_boxes(image: np.ndarray, color: BoxColor) -> List[CropBox]:
    """Detect Paint-style outline rectangles for the project box-color convention."""
    mask = _outline_mask(image, color)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    img_h, img_w = image.shape[:2]
    boxes: List[CropBox] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if w < 10 or h < 10:
            continue
        if area < 300 or area > img_w * img_h * 0.9:
            continue

        roi_mask = mask[y : y + h, x : x + w]
        fill_ratio = float(np.count_nonzero(roi_mask)) / float(area)
        max_fill_ratio = 0.78 if area < 800 else 0.55
        if fill_ratio > max_fill_ratio:
            continue

        band = max(2, min(6, min(w, h) // 8))
        top = np.count_nonzero(roi_mask[:band, :]) / float(band * w)
        bottom = np.count_nonzero(roi_mask[-band:, :]) / float(band * w)
        left = np.count_nonzero(roi_mask[:, :band]) / float(band * h)
        right = np.count_nonzero(roi_mask[:, -band:]) / float(band * h)
        complete_outline = min(top, bottom, left, right) >= 0.35
        button_like_outline = (
            w >= 40
            and h >= 20
            and top >= 0.25
            and bottom >= 0.25
            and min(left, right) >= 0.02
            and max(left, right) >= 0.08
        )
        if not complete_outline and not button_like_outline:
            print(f'Box skipped: w={w}, h={h}, fill={fill_ratio}, top={top}, bottom={bottom}, left={left}, right={right}')
            continue

        boxes.append(CropBox(x, y, w, h))

    return _dedupe_boxes(sorted(boxes, key=lambda box: (box.y, box.x)))


def crop_inside_blue_box(image: np.ndarray, box: CropBox) -> np.ndarray:
    return crop_inside_colored_box(image, box, "blue")


def crop_inside_colored_box(image: np.ndarray, box: CropBox, color: BoxColor) -> np.ndarray:
    roi = image[box.y : box.y + box.height, box.x : box.x + box.width]
    mask = _outline_mask(roi, color)

    projected_crop = _crop_by_outline_projection(roi, mask)
    if projected_crop is not None:
        return projected_crop

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


def _crop_by_outline_projection(roi: np.ndarray, mask: np.ndarray) -> Optional[np.ndarray]:
    height, width = mask.shape[:2]
    if width <= 2 or height <= 2:
        return None

    row_counts = np.count_nonzero(mask, axis=1)
    col_counts = np.count_nonzero(mask, axis=0)
    top = _leading_outline_thickness(row_counts, width)
    bottom = _trailing_outline_thickness(row_counts, width)
    left = _leading_outline_thickness(col_counts, height)
    right = _trailing_outline_thickness(col_counts, height)
    if not any((top, bottom, left, right)):
        return None

    x_min = left
    x_max = width - right - 1
    y_min = top
    y_max = height - bottom - 1
    if x_min > x_max or y_min > y_max:
        return None

    crop = roi[y_min : y_max + 1, x_min : x_max + 1]
    if crop.size == 0:
        return None
    return crop


def _leading_outline_thickness(counts: np.ndarray, span: int) -> int:
    threshold = max(2, int(round(span * 0.60)))
    limit = max(1, len(counts) // 2)
    thickness = 0
    for value in counts[:limit]:
        if int(value) < threshold:
            break
        thickness += 1
    return thickness


def _trailing_outline_thickness(counts: np.ndarray, span: int) -> int:
    threshold = max(2, int(round(span * 0.60)))
    limit = max(1, len(counts) // 2)
    thickness = 0
    for value in counts[::-1][:limit]:
        if int(value) < threshold:
            break
        thickness += 1
    return thickness


def write_blue_crop_review(
    screenshot_paths: Sequence[Path],
    output_dir: Path,
    *,
    source_folder: Optional[Path] = None,
) -> List[Path]:
    """Write serial-numbered blue-box crops, a manifest, and a contact sheet."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    manifest_lines = []
    if source_folder is not None:
        manifest_lines.append(f"source_folder={source_folder}")
        manifest_lines.append("")

    serial = 1
    for screen_index, screenshot_path in enumerate(screenshot_paths, start=1):
        image = read_image(screenshot_path, cv2.IMREAD_COLOR)
        boxes = find_blue_boxes(image)
        for box_index, box in enumerate(boxes, start=1):
            crop = crop_inside_blue_box(image, box)
            if crop.size == 0:
                continue

            filename = (
                f"{serial:03d}_screen{screen_index:02d}_blue{box_index:02d}_"
                f"{box.x}_{box.y}_{box.width}x{box.height}.png"
            )
            dest_path = output_dir / filename
            write_image(dest_path, crop)
            saved.append(dest_path)
            manifest_lines.append(
                f"{serial:03d}: file={filename} source={screenshot_path.name} "
                f"box=({box.x},{box.y},{box.width},{box.height}) crop={crop.shape[1]}x{crop.shape[0]}"
            )
            serial += 1

    (output_dir / "manifest.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    _write_contact_sheet(saved, output_dir / "000_contact_sheet.png")
    return saved


def _blue_outline_mask(image: np.ndarray) -> np.ndarray:
    """Mask the dark blue/primary blue strokes Paint uses for manual crop boxes."""
    return _outline_mask(image, "blue")


def _outline_mask(image: np.ndarray, color: BoxColor) -> np.ndarray:
    if color == "blue":
        return _blue_outline_mask_impl(image)
    if color == "red":
        return _red_outline_mask(image)
    if color == "green":
        return _green_outline_mask(image)
    raise ValueError(f"Unsupported box color: {color}")


def _blue_outline_mask_impl(image: np.ndarray) -> np.ndarray:
    blue, green, red = cv2.split(image)

    # Windows Paint dark-blue outline: RGB #3F48CC, stored by OpenCV as BGR
    # (204, 72, 63). The project convention is to draw boxes with this exact
    # Paint color and no anti-aliasing, so keep the mask exact to avoid picking
    # up blue in the game UI.
    mask = (
        (blue == 204)
        & (green == 72)
        & (red == 63)
    )
    return mask.astype(np.uint8) * 255


def _red_outline_mask(image: np.ndarray) -> np.ndarray:
    blue, green, red = cv2.split(image)
    strongest_other = np.maximum(blue, green).astype(np.int16)
    red_i = red.astype(np.int16)
    mask = (
        (red >= 145)
        & (blue <= 140)
        & (green <= 140)
        & ((red_i - strongest_other) >= 45)
    )
    return mask.astype(np.uint8) * 255


def _green_outline_mask(image: np.ndarray) -> np.ndarray:
    blue, green, red = cv2.split(image)
    strongest_other = np.maximum(blue, red).astype(np.int16)
    green_i = green.astype(np.int16)
    mask = (
        (green >= 130)
        & (blue <= 150)
        & (red <= 150)
        & ((green_i - strongest_other) >= 35)
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


def _write_contact_sheet(paths: Sequence[Path], output_path: Path) -> None:
    if not paths:
        tiny = np.full((80, 240, 3), 245, dtype=np.uint8)
        cv2.putText(tiny, "No blue boxes", (18, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (70, 70, 70), 1, cv2.LINE_AA)
        write_image(output_path, tiny)
        return

    thumbs = []
    labels = []
    for path in paths:
        image = read_image(path, cv2.IMREAD_COLOR)
        h, w = image.shape[:2]
        scale = min(1.0, 180.0 / max(w, h))
        resized = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        thumbs.append(resized)
        labels.append(path.name[:34])

    columns = min(3, len(thumbs))
    cell_w = 220
    cell_h = 220
    rows = (len(thumbs) + columns - 1) // columns
    sheet = np.full((rows * cell_h, columns * cell_w, 3), 245, dtype=np.uint8)

    for index, thumb in enumerate(thumbs):
        row = index // columns
        col = index % columns
        x0 = col * cell_w
        y0 = row * cell_h
        cv2.putText(sheet, labels[index], (x0 + 10, y0 + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (45, 45, 45), 1, cv2.LINE_AA)
        h, w = thumb.shape[:2]
        x = x0 + (cell_w - w) // 2
        y = y0 + 42 + (cell_h - 52 - h) // 2
        sheet[y : y + h, x : x + w] = thumb
        cv2.rectangle(sheet, (x0 + 4, y0 + 4), (x0 + cell_w - 5, y0 + cell_h - 5), (205, 205, 205), 1)

    write_image(output_path, sheet)


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
