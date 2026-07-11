from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads2.tools.render_x_geometry_debug_sheet import parse_rows
from ads2.tools.scan_x_geometry_candidates import (
    draw_match_debug,
    gate_by_name,
    mask_from_hsv,
    read_bgr,
    two_stroke_fit,
    write_png,
)


def parse_box(value: str):
    box = ast.literal_eval(value)
    if not isinstance(box, tuple) or len(box) != 4:
        raise argparse.ArgumentTypeError("box must look like '(x, y, w, h)'")
    return tuple(int(v) for v in box)


def row_matches(row, contains, boxes):
    if not contains and not boxes:
        return False
    if contains and not any(text in row["path"].as_posix() for text in contains):
        return False
    if boxes and tuple(row["box"]) not in boxes:
        return False
    return True


def crop_bounds(image, row, pad: int, roi_top_ratio: float):
    h, w = image.shape[:2]
    x, y, bw, bh = row["box"]
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(w, x + bw + pad)
    y1 = min(int(h * roi_top_ratio), y + bh + pad)
    return x0, y0, x1, y1


def make_gate_and_component_views(image, row, bounds, roi_top_ratio: float):
    x0, y0, x1, y1 = bounds
    gate = gate_by_name(row["gate"])
    if gate is None:
        blank = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
        return blank, blank

    h, _w = image.shape[:2]
    roi_h = int(h * roi_top_ratio)
    hsv_roi = cv2.cvtColor(image[:roi_h, :], cv2.COLOR_BGR2HSV)
    mask = mask_from_hsv(hsv_roi, gate)
    gate_crop = cv2.cvtColor(mask[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)

    x, y, bw, bh = row["box"]
    comp = component_mask_for_row(mask, row)
    comp_crop = cv2.cvtColor(comp[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
    return gate_crop, comp_crop, comp


def component_mask_for_row(mask, row):
    x, y, bw, bh = row["box"]
    labels_count, labels, _stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if labels_count <= 1:
        return np.zeros_like(mask)
    box_labels = labels[y : y + bh, x : x + bw]
    positive = box_labels[box_labels > 0]
    if positive.size == 0:
        return np.zeros_like(mask)
    label = int(np.bincount(positive).argmax())
    return np.where(labels == label, 255, 0).astype(np.uint8)


def two_stroke_views(comp_full, row, bounds):
    x0, y0, x1, y1 = bounds
    x, y, bw, bh = row["box"]
    component_crop = comp_full[y : y + bh, x : x + bw]
    ys, xs = np.where(component_crop > 0)
    blank = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
    if len(xs) < 6:
        return blank, blank, blank

    points = np.column_stack(
        (
            xs.astype(np.float32) - (bw - 1) / 2.0,
            ys.astype(np.float32) - (bh - 1) / 2.0,
        )
    )
    angle = float(row["angle_down"])
    theta_down = np.deg2rad(angle)
    theta_up = np.deg2rad(float(row["angle_up"]))
    axis = {
        "angle": angle,
        "angle_up": float(row["angle_up"]),
        "normal_down": np.array([-np.sin(theta_down), np.cos(theta_down)], dtype=np.float32),
        "normal_up": np.array([-np.sin(theta_up), np.cos(theta_up)], dtype=np.float32),
        "unit_down": np.array([np.cos(theta_down), np.sin(theta_down)], dtype=np.float32),
        "unit_up": np.array([np.cos(theta_up), np.sin(theta_up)], dtype=np.float32),
    }
    profile = {
        "axis_span_down_px": float(row.get("axis_span_down_px", 0.0)),
        "axis_span_up_px": float(row.get("axis_span_up_px", 0.0)),
    }
    _fit, model_crop = two_stroke_fit(component_crop, points, axis, profile, min_dim=max(1, min(bw, bh)))
    if model_crop is None:
        return blank, blank, blank

    model_full = np.zeros_like(comp_full, dtype=bool)
    model_full[y : y + bh, x : x + bw] = model_crop
    comp_bool = comp_full > 0
    outside = comp_bool & ~model_full
    missing = model_full & ~comp_bool

    yy, xx = np.indices(comp_full.shape)
    cx = x + bw / 2.0
    cy = y + bh / 2.0
    radius = max(2.0, 1.5 * float(row.get("stroke_width", _fit.get("stroke_width", 2.0))))
    center_region = ((xx - cx) ** 2 + (yy - cy) ** 2) <= radius * radius
    center_extra = outside & center_region

    model_view = cv2.cvtColor((model_full[y0:y1, x0:x1].astype(np.uint8) * 255), cv2.COLOR_GRAY2BGR)
    outside_view = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
    outside_view[outside[y0:y1, x0:x1]] = (0, 0, 255)
    outside_view[missing[y0:y1, x0:x1]] = (255, 0, 0)
    center_view = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
    center_view[center_region[y0:y1, x0:x1]] = (80, 80, 80)
    center_view[center_extra[y0:y1, x0:x1]] = (0, 0, 255)
    return model_view, outside_view, center_view


def fit_panel(image, size=(180, 140)):
    return cv2.resize(image, size, interpolation=cv2.INTER_NEAREST)


def put_label(tile, lines):
    tile = cv2.copyMakeBorder(tile, 76, 6, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    y = 18
    for line in lines:
        cv2.putText(tile, line[:58], (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 0, 0), 1, cv2.LINE_AA)
        y += 17
    return tile


def render_row(row, *, roi_top_ratio: float, pad: int):
    image = read_bgr(row["path"])
    if image is None:
        return None
    bounds = crop_bounds(image, row, pad, roi_top_ratio)
    x0, y0, x1, y1 = bounds
    x, y, bw, bh = row["box"]

    original = image[y0:y1, x0:x1].copy()
    cv2.rectangle(original, (x - x0, y - y0), (x - x0 + bw, y - y0 + bh), (0, 0, 255), 2)
    gate_view, comp_view, comp_full = make_gate_and_component_views(image, row, bounds, roi_top_ratio)
    model_view, outside_view, center_view = two_stroke_views(comp_full, row, bounds)
    overlay = image[y0:y1, x0:x1].copy()
    overlay = draw_match_debug(overlay, image, row, x0=x0, y0=y0, roi_top_ratio=roi_top_ratio)
    cv2.rectangle(overlay, (x - x0, y - y0), (x - x0 + bw, y - y0 + bh), (0, 0, 255), 2)

    labels = [
        f"score={row['score']:.3f} gate={row['gate']} box={row['box']}",
        f"u={row['axis_union']:.3f} b={row['axis_balance']:.3f} l={row['length_ratio']:.3f} fill={row['fill']:.3f}",
        f"span={min(row.get('axis_span_down_px', 0), row.get('axis_span_up_px', 0)):.2f} arm={row.get('min_arm_extent_px', 0):.2f} cov={row.get('min_arm_coverage', 0):.2f}",
        f"center={row.get('center_pixels', 0)} thick={row.get('center_thickness_ratio', 0):.3f}",
        f"fit={row.get('fit_error', 0):.3f} extra={row.get('extra_error', 0):.3f} missing={row.get('missing_error', 0):.3f} cextra={row.get('center_extra_error', 0):.3f}",
    ]
    panels = [
        put_label(fit_panel(original), ["original", *labels]),
        put_label(fit_panel(gate_view), ["gate mask", row["path"].name]),
        put_label(fit_panel(comp_view), ["component mask", row["path"].parent.name[:52]]),
        put_label(fit_panel(model_view), ["two-stroke model"]),
        put_label(fit_panel(outside_view), ["red=component outside", "blue=model missing"]),
        put_label(fit_panel(center_view), ["center extra region"]),
        put_label(fit_panel(overlay), ["geometry overlay", row["path"].as_posix()[-58:]]),
    ]
    return np.hstack(panels)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render per-candidate X geometry debug panels.")
    parser.add_argument("scan_dir", type=Path)
    parser.add_argument("--contains", nargs="*", default=[])
    parser.add_argument("--box", type=parse_box, action="append", default=[])
    parser.add_argument("--lowest", type=int, default=0)
    parser.add_argument("--top", type=int, default=0)
    parser.add_argument("--pad", type=int, default=36)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    rows, roi_top_ratio = parse_rows(args.scan_dir / "scan_report.md")
    selected = [row for row in rows if row_matches(row, args.contains, set(args.box))]
    if args.top > 0:
        selected.extend(sorted(rows, key=lambda row: row["score"], reverse=True)[: args.top])
    if args.lowest > 0:
        selected.extend(sorted(rows, key=lambda row: row["score"])[: args.lowest])

    unique = []
    seen = set()
    for row in selected:
        key = (row["path"], row["box"], row["gate"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    if not unique:
        raise SystemExit("No matching rows.")

    rendered = [render_row(row, roi_top_ratio=roi_top_ratio, pad=args.pad) for row in unique]
    rendered = [row for row in rendered if row is not None]
    if not rendered:
        raise SystemExit("No renderable rows.")

    sheet = np.vstack(rendered)
    output = args.output or (args.scan_dir / "candidate_debug.png")
    write_png(output, sheet)
    print("candidate debug:", output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
