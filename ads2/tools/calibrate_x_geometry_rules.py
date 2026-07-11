from __future__ import annotations

import argparse
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


DEFAULT_X_NAMES = (
    "ad_issue_20260606_042353_roi_0.png",
    "ad_issue_20260606_042429_roi_0.png",
    "ad_issue_20260606_043419_roi_0.png",
    "ad_issue_20260606_044653_roi_0.png",
    "ad_issue_20260606_044717_roi_0.png",
    "ad_issue_20260606_052002_roi_15.png",
    "ad_issue_20260606_052302_roi_0.png",
    "close_2.png",
    "close_7.png",
    "close_12.png",
    "close_14.png",
    "close_17.png",
    "close_24.png",
    "close_25.png",
    "close_x_end.png",
)


@dataclass(frozen=True)
class GateConfig:
    name: str
    mode: str
    saturation_max: int = 255
    saturation_min: int = 0
    value_min: int = 0
    value_max: int = 255
    hue_min: int = 0
    hue_max: int = 179


GATES = (
    GateConfig("white_strict", "white", saturation_max=60, value_min=170),
    GateConfig("white_soft", "white", saturation_max=90, value_min=140),
    GateConfig("bright", "bright", value_min=150),
    GateConfig("cyan_soft", "hue", hue_min=70, hue_max=115, saturation_min=60, value_min=120),
    GateConfig("cyan_strict", "hue", hue_min=70, hue_max=115, saturation_min=140, value_min=180),
    GateConfig("black_strict", "black", saturation_max=90, value_max=115),
    GateConfig("black_soft", "black", saturation_max=130, value_max=140),
)


def read_bgr(path: Path):
    raw = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        return None
    if raw.ndim == 2:
        return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    return raw[:, :, :3]


def write_png(path: Path, image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    if ok:
        buffer.tofile(str(path))


def build_mask(bgr, gate: GateConfig):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    if gate.mode == "white":
        cond = (hsv[:, :, 1] <= gate.saturation_max) & (hsv[:, :, 2] >= gate.value_min)
    elif gate.mode == "black":
        cond = (hsv[:, :, 1] <= gate.saturation_max) & (hsv[:, :, 2] <= gate.value_max)
    elif gate.mode == "bright":
        cond = hsv[:, :, 2] >= gate.value_min
    elif gate.mode == "hue":
        cond = (
            (hsv[:, :, 0] >= gate.hue_min)
            & (hsv[:, :, 0] <= gate.hue_max)
            & (hsv[:, :, 1] >= gate.saturation_min)
            & (hsv[:, :, 1] <= gate.saturation_max)
            & (hsv[:, :, 2] >= gate.value_min)
            & (hsv[:, :, 2] <= gate.value_max)
        )
    else:
        raise ValueError(gate.mode)
    mask = cond.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    return mask


def mask_bbox(mask):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def line_angle(line) -> float:
    x1, y1, x2, y2 = line
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    if angle < 0:
        angle += 180.0
    if angle >= 180.0:
        angle -= 180.0
    return angle


def line_length(line) -> float:
    x1, y1, x2, y2 = line
    return math.hypot(x2 - x1, y2 - y1)


def line_segment_through_box(width: int, height: int, angle: float):
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    theta = math.radians(angle)
    dx = math.cos(theta)
    dy = math.sin(theta)
    points = []
    if abs(dx) > 1e-6:
        for x in (0.0, float(width - 1)):
            t = (x - cx) / dx
            y = cy + t * dy
            if 0 <= y <= height - 1:
                points.append((x, y))
    if abs(dy) > 1e-6:
        for y in (0.0, float(height - 1)):
            t = (y - cy) / dy
            x = cx + t * dx
            if 0 <= x <= width - 1:
                points.append((x, y))
    if len(points) < 2:
        return (0, int(round(cy)), width - 1, int(round(cy)))
    points.sort(key=lambda pt: (pt[0], pt[1]))
    first = points[0]
    last = points[-1]
    return (
        int(round(first[0])),
        int(round(first[1])),
        int(round(last[0])),
        int(round(last[1])),
    )


def intersection(line_a, line_b) -> Optional[tuple[float, float]]:
    x1, y1, x2, y2 = map(float, line_a)
    x3, y3, x4, y4 = map(float, line_b)
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-6:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return px, py


def fit_cross_axes(mask):
    bbox = mask_bbox(mask)
    if bbox is None:
        return None
    x, y, w, h = bbox
    crop = mask[y : y + h, x : x + w]
    ys, xs = np.where(crop > 0)
    if len(xs) < 6:
        return None

    points = np.column_stack(
        (
            xs.astype(np.float32) - (w - 1) / 2.0,
            ys.astype(np.float32) - (h - 1) / 2.0,
        )
    )
    min_dim = max(1, min(w, h))
    diag = max(1.0, math.hypot(w, h))
    centroid_offset = float(np.linalg.norm(points.mean(axis=0)) / diag)
    tolerance = max(1.2, min_dim * 0.16)
    best = None
    for angle in np.arange(36.0, 55.1, 0.5):
        theta_down = math.radians(angle)
        theta_up = math.radians(180.0 - angle)
        normal_down = np.array([-math.sin(theta_down), math.cos(theta_down)], dtype=np.float32)
        normal_up = np.array([-math.sin(theta_up), math.cos(theta_up)], dtype=np.float32)
        unit_down = np.array([math.cos(theta_down), math.sin(theta_down)], dtype=np.float32)
        unit_up = np.array([math.cos(theta_up), math.sin(theta_up)], dtype=np.float32)

        dist_down = np.abs(points @ normal_down)
        dist_up = np.abs(points @ normal_up)
        near_down = dist_down <= tolerance
        near_up = dist_up <= tolerance
        union = near_down | near_up
        union_ratio = float(union.sum() / len(points))
        if union_ratio < 0.50:
            continue

        assigned_down = near_down & (dist_down <= dist_up)
        assigned_up = near_up & (dist_up < dist_down)
        # Center pixels may be near both lines; count them for both balances.
        count_down = max(int(assigned_down.sum()), int((near_down & near_up).sum()))
        count_up = max(int(assigned_up.sum()), int((near_down & near_up).sum()))
        if count_down == 0 or count_up == 0:
            continue

        proj_down = points[near_down] @ unit_down
        proj_up = points[near_up] @ unit_up
        extent_down = float(np.percentile(proj_down, 95) - np.percentile(proj_down, 5)) if len(proj_down) else 0.0
        extent_up = float(np.percentile(proj_up, 95) - np.percentile(proj_up, 5)) if len(proj_up) else 0.0
        length_ratio = min(extent_down, extent_up) / max(extent_down, extent_up, 1e-6)
        balance = min(count_down, count_up) / max(count_down, count_up)
        angle_delta = abs(angle - 45.0)
        angle_score = max(0.0, 1.0 - angle_delta / 15.0)
        center_score = max(0.0, 1.0 - centroid_offset / 0.35)
        score = union_ratio * 0.30 + balance * 0.22 + length_ratio * 0.23 + angle_score * 0.15 + center_score * 0.10
        candidate = {
            "score": score,
            "method": "axis",
            "bbox": (x, y, w, h),
            "line_down": tuple(v + (x if i % 2 == 0 else y) for i, v in enumerate(line_segment_through_box(w, h, angle))),
            "line_up": tuple(v + (x if i % 2 == 0 else y) for i, v in enumerate(line_segment_through_box(w, h, 180.0 - angle))),
            "angle_down": angle,
            "angle_up": 180.0 - angle,
            "length_down": extent_down,
            "length_up": extent_up,
            "length_ratio": length_ratio,
            "center_offset": centroid_offset,
            "angle_delta": angle_delta,
            "orth_delta": 0.0,
            "fill": float((crop > 0).sum() / max(1, w * h)),
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def detect_lines(mask):
    h, w = mask.shape[:2]
    edges = cv2.Canny(mask, 20, 100)
    min_dim = min(h, w)
    raw = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=max(2, int(min_dim * 0.12)),
        minLineLength=max(3, int(min_dim * 0.25)),
        maxLineGap=max(3, int(min_dim * 0.30)),
    )
    if raw is None:
        return []
    raw = raw.reshape(-1, 4)
    lines = []
    for item in raw:
        line = tuple(int(v) for v in item)
        length = line_length(line)
        if length >= 4:
            lines.append((line, line_angle(line), length))
    return lines


def best_x_pair(mask):
    bbox = mask_bbox(mask)
    if bbox is None:
        return None
    axis_best = fit_cross_axes(mask)
    x, y, w, h = bbox
    crop = mask[y : y + h, x : x + w]
    lines = detect_lines(crop)
    if not lines:
        return axis_best

    down = [entry for entry in lines if 20 <= entry[1] <= 80]
    up = [entry for entry in lines if 100 <= entry[1] <= 160]
    if not down or not up:
        return axis_best

    center = (w / 2.0, h / 2.0)
    diag = max(1.0, math.hypot(w, h))
    best = None
    for line_a, angle_a, len_a in down:
        for line_b, angle_b, len_b in up:
            point = intersection(line_a, line_b)
            if point is None:
                continue
            cx, cy = point
            center_offset = math.hypot(cx - center[0], cy - center[1]) / diag
            length_ratio = min(len_a, len_b) / max(len_a, len_b)
            angle_delta = max(abs(angle_a - 45.0), abs(angle_b - 135.0))
            pair_angle = abs(angle_b - angle_a)
            orth_delta = abs(pair_angle - 90.0)
            angle_score = max(0.0, 1.0 - angle_delta / 45.0)
            orth_score = max(0.0, 1.0 - orth_delta / 45.0)
            center_score = max(0.0, 1.0 - center_offset / 0.45)
            score = angle_score * 0.35 + orth_score * 0.20 + length_ratio * 0.25 + center_score * 0.20
            candidate = {
                "score": score,
                "method": "hough",
                "bbox": (x, y, w, h),
                "line_down": (line_a[0] + x, line_a[1] + y, line_a[2] + x, line_a[3] + y),
                "line_up": (line_b[0] + x, line_b[1] + y, line_b[2] + x, line_b[3] + y),
                "angle_down": angle_a,
                "angle_up": angle_b,
                "length_down": len_a,
                "length_up": len_b,
                "length_ratio": length_ratio,
                "center_offset": center_offset,
                "angle_delta": angle_delta,
                "orth_delta": orth_delta,
                "fill": float((crop > 0).sum() / max(1, w * h)),
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate
    if axis_best is not None and (best is None or axis_best["score"] > best["score"]):
        return axis_best
    return best


def analyze_image(path: Path):
    image = read_bgr(path)
    if image is None:
        return None
    candidates = []
    for gate in GATES:
        mask = build_mask(image, gate)
        masks = [mask]
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            if area < 6:
                continue
            component = np.zeros_like(mask)
            component[labels == label] = 255
            masks.append(component)
        for candidate_mask in masks:
            candidate = best_x_pair(candidate_mask)
            if candidate is None:
                continue
            candidate["gate"] = gate.name
            candidate["path"] = path
            candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[0]


def copy_samples(source_dir: Path, sample_dir: Path, names: tuple[str, ...]) -> list[Path]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in names:
        source = source_dir / name
        if not source.exists():
            continue
        target = sample_dir / name
        shutil.copy2(source, target)
        copied.append(target)
    return copied


def make_contact_sheet(paths: list[Path], output_path: Path) -> None:
    tiles = []
    for path in paths:
        img = read_bgr(path)
        if img is None:
            continue
        h, w = img.shape[:2]
        scale = max(1, min(6, 150 // max(h, w)))
        tile = cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
        tile = cv2.copyMakeBorder(tile, 26, 6, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(tile, path.name[:32], (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(tile)
    if not tiles:
        return
    cols = 3
    max_h = max(tile.shape[0] for tile in tiles)
    max_w = max(tile.shape[1] for tile in tiles)
    padded = [
        cv2.copyMakeBorder(tile, 0, max_h - tile.shape[0], 0, max_w - tile.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))
        for tile in tiles
    ]
    blank = np.full_like(padded[0], 255)
    while len(padded) % cols:
        padded.append(blank.copy())
    sheet = np.vstack([np.hstack(padded[i : i + cols]) for i in range(0, len(padded), cols)])
    write_png(output_path, sheet)


def make_calibration_sheet(rows, output_path: Path) -> None:
    tiles = []
    for row in rows:
        img = read_bgr(row["path"])
        if img is None:
            continue
        x, y, w, h = row["bbox"]
        annotated = img.copy()
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 0, 255), 1)
        cv2.line(annotated, row["line_down"][:2], row["line_down"][2:], (0, 255, 0), 1, cv2.LINE_AA)
        cv2.line(annotated, row["line_up"][:2], row["line_up"][2:], (255, 0, 0), 1, cv2.LINE_AA)
        scale = max(1, min(6, 150 // max(annotated.shape[:2])))
        tile = cv2.resize(annotated, (annotated.shape[1] * scale, annotated.shape[0] * scale), interpolation=cv2.INTER_NEAREST)
        tile = cv2.copyMakeBorder(tile, 48, 8, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(
            tile,
            f"{row['score']:.3f} {row['gate']} {row['method']}",
            (8, 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            f"a={row['angle_down']:.1f}/{row['angle_up']:.1f} r={row['length_ratio']:.2f} c={row['center_offset']:.2f}",
            (8, 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        tiles.append(tile)
    if not tiles:
        return
    cols = 3
    max_h = max(tile.shape[0] for tile in tiles)
    max_w = max(tile.shape[1] for tile in tiles)
    padded = [
        cv2.copyMakeBorder(tile, 0, max_h - tile.shape[0], 0, max_w - tile.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))
        for tile in tiles
    ]
    blank = np.full_like(padded[0], 255)
    while len(padded) % cols:
        padded.append(blank.copy())
    sheet = np.vstack([np.hstack(padded[i : i + cols]) for i in range(0, len(padded), cols)])
    write_png(output_path, sheet)


def summarize_ranges(rows):
    if not rows:
        return []
    fields = ("angle_down", "angle_up", "angle_delta", "orth_delta", "length_ratio", "center_offset", "fill")
    lines = ["## Observed Ranges", ""]
    for field in fields:
        values = [row[field] for row in rows]
        lines.append(f"- {field}: min={min(values):.3f}, median={float(np.median(values)):.3f}, max={max(values):.3f}")
    lines.extend(
        [
            "",
            "## Suggested Starting Filters",
            "",
            f"- angle_down: {math.floor(min(row['angle_down'] for row in rows) - 2)}..{math.ceil(max(row['angle_down'] for row in rows) + 2)}",
            f"- angle_up: {math.floor(min(row['angle_up'] for row in rows) - 2)}..{math.ceil(max(row['angle_up'] for row in rows) + 2)}",
            f"- max_angle_delta: {math.ceil(max(row['angle_delta'] for row in rows) + 2)}",
            f"- max_orth_delta: {math.ceil(max(row['orth_delta'] for row in rows) + 2)}",
            f"- min_length_ratio: {max(0.0, min(row['length_ratio'] for row in rows) - 0.08):.2f}",
            f"- max_center_offset: {max(row['center_offset'] for row in rows) + 0.05:.2f}",
        ]
    )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate strict geometric X rules from known close templates.")
    parser.add_argument("--source-dir", type=Path, default=Path("ads2/assets/1_templates/close_icons"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ads2/assets/review_crops/close_glyph_candidates/x_rule_calibration"),
    )
    parser.add_argument("--names", nargs="*", default=list(DEFAULT_X_NAMES))
    args = parser.parse_args()

    sample_dir = args.output_dir / "samples"
    sample_paths = copy_samples(args.source_dir, sample_dir, tuple(args.names))
    rows = []
    missing = []
    for name in args.names:
        source = args.source_dir / name
        if not source.exists():
            missing.append(name)
    for path in sample_paths:
        row = analyze_image(path)
        if row is not None:
            rows.append(row)
    analyzed_names = {row["path"].name for row in rows}
    not_analyzed = [path.name for path in sample_paths if path.name not in analyzed_names]
    rows.sort(key=lambda item: item["path"].name)

    make_contact_sheet(sample_paths, args.output_dir / "x_template_contact_sheet.png")
    make_calibration_sheet(rows, args.output_dir / "x_line_calibration_sheet.png")

    report = [
        "# X Line Calibration",
        "",
        f"Source dir: `{args.source_dir.as_posix()}`",
        f"Sample dir: `{sample_dir.as_posix()}`",
        f"Samples copied: {len(sample_paths)}",
        f"Samples analyzed: {len(rows)}",
        f"Missing: {', '.join(missing) if missing else 'none'}",
        f"Not analyzed: {', '.join(not_analyzed) if not_analyzed else 'none'}",
        "",
        "| file | score | method | gate | bbox | angle_down | angle_up | angle_delta | orth_delta | length_ratio | center_offset | fill |",
        "|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| `{row['path'].name}` | {row['score']:.3f} | {row['method']} | {row['gate']} | `{row['bbox']}` | "
            f"{row['angle_down']:.2f} | {row['angle_up']:.2f} | {row['angle_delta']:.2f} | "
            f"{row['orth_delta']:.2f} | {row['length_ratio']:.3f} | {row['center_offset']:.3f} | {row['fill']:.3f} |"
        )
    report.extend(["", *summarize_ranges(rows), ""])
    (args.output_dir / "x_line_calibration.md").write_text("\n".join(report), encoding="utf-8")

    print(args.output_dir.resolve())
    print("samples:", sample_dir.resolve())
    print("report:", (args.output_dir / "x_line_calibration.md").resolve())
    print("sheet:", (args.output_dir / "x_line_calibration_sheet.png").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
