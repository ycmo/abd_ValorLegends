from __future__ import annotations

import argparse
import math
import os
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads2.tools.calibrate_x_geometry_rules import GATES

DIAGONAL_MASK_CACHE = {}

PRESETS = {
    "strict": {},
    "relaxed-bg": {
        "max_size": 52,
        "min_aspect": 0.65,
        "max_aspect": 1.55,
    },
    "relaxed-bright": {
        "gates": ["white_strict", "white_soft", "black_strict", "black_soft", "bright"],
        "min_size": 8,
        "max_size": 52,
        "min_aspect": 0.55,
        "max_aspect": 1.80,
        "min_score": 0.78,
        "prefilter_min_score": 0.45,
        "prefilter_min_diag_each": 0.25,
        "prefilter_min_union": 0.45,
        "min_axis_union": 0.45,
        "min_axis_balance": 0.25,
    },
    "right-bright": {
        "gates": ["white_strict", "white_soft", "black_strict", "black_soft", "bright"],
        "max_size": 52,
        "min_aspect": 0.65,
        "max_aspect": 1.55,
        "prefilter_min_score": 0.45,
        "prefilter_min_diag_each": 0.25,
        "prefilter_min_union": 0.45,
        "min_x_ratio": 0.55,
    },
    "close12-loose": {
        "max_size": 52,
        "max_fill": 0.55,
        "prefilter_min_score": 0.45,
        "prefilter_min_diag_each": 0.20,
        "prefilter_min_union": 0.45,
    },
    "close12-weighted": {
        "max_size": 52,
        "max_fill": 0.55,
        "prefilter_min_score": 0.45,
        "prefilter_min_diag_each": 0.20,
        "prefilter_min_union": 0.45,
        "min_score": 0.0,
        "min_axis_union": 0.0,
        "min_axis_balance": 0.0,
        "min_length_ratio": 0.0,
        "weight_continuity": 0.25,
    },
}


def provided_cli_options(argv):
    return {token.split("=", 1)[0] for token in argv if token.startswith("--")}


def apply_preset(args, provided_options):
    for key, value in PRESETS[args.preset].items():
        option = "--" + key.replace("_", "-")
        if option not in provided_options:
            setattr(args, key, value)


def build_axis_cache(args):
    axes = []
    for angle in np.arange(args.angle_down_min, args.angle_down_max + 0.001, args.angle_step):
        angle = float(angle)
        angle_up = 180.0 - angle
        if not (args.angle_up_min <= angle_up <= args.angle_up_max):
            continue
        angle_delta = max(abs(angle - 45.0), abs(angle_up - 135.0))
        if angle_delta > args.max_angle_delta:
            continue
        theta_down = math.radians(angle)
        theta_up = math.radians(angle_up)
        axes.append(
            {
                "angle": angle,
                "angle_up": angle_up,
                "angle_delta": angle_delta,
                "normal_down": np.array([-math.sin(theta_down), math.cos(theta_down)], dtype=np.float32),
                "normal_up": np.array([-math.sin(theta_up), math.cos(theta_up)], dtype=np.float32),
                "unit_down": np.array([math.cos(theta_down), math.sin(theta_down)], dtype=np.float32),
                "unit_up": np.array([math.cos(theta_up), math.sin(theta_up)], dtype=np.float32),
            }
        )
    return axes


def read_bgr(path: Path):
    raw = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        return None
    if raw.ndim == 2:
        return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    return raw[:, :, :3]


def write_png(path: Path, image) -> None:
    ok, buffer = cv2.imencode(".png", image)
    if ok:
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer.tofile(str(path))


def color_mask(bgr, *, mode: str, saturation_max: int, value_min: int, value_max: int):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    if mode == "white":
        mask = (hsv[:, :, 1] <= saturation_max) & (hsv[:, :, 2] >= value_min)
    elif mode == "black":
        mask = (hsv[:, :, 1] <= saturation_max) & (hsv[:, :, 2] <= value_max)
    else:
        raise ValueError(f"Unsupported mode: {mode}")
    mask = mask.astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def mask_from_hsv(hsv, gate):
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
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))


def gate_by_name(name: str):
    for gate in GATES:
        if gate.name == name:
            return gate
    return None


def diagonal_masks(height: int, width: int):
    key = (height, width)
    masks = DIAGONAL_MASK_CACHE.get(key)
    if masks is not None:
        return masks
    yy, xx = np.indices((height, width))
    tolerance = max(1.5, min(width, height) * 0.14)
    diag_down = np.abs(yy - (height - 1) * xx / max(1, width - 1)) <= tolerance
    diag_up = np.abs(yy - ((height - 1) - (height - 1) * xx / max(1, width - 1))) <= tolerance
    DIAGONAL_MASK_CACHE[key] = (diag_down, diag_up)
    return diag_down, diag_up


def diagonal_score(mask):
    h, w = mask.shape[:2]
    if h < 4 or w < 4:
        return None
    diag_down, diag_up = diagonal_masks(h, w)
    pix = mask > 0
    pixel_count = int(pix.sum())
    if pixel_count == 0:
        return None

    down_ratio = float((pix & diag_down).sum() / pixel_count)
    up_ratio = float((pix & diag_up).sum() / pixel_count)
    union_ratio = float((pix & (diag_down | diag_up)).sum() / pixel_count)

    center = (w // 2, h // 2)
    center_radius = max(2, int(round(min(w, h) * 0.18)))
    center_area = pix[
        max(0, center[1] - center_radius) : min(h, center[1] + center_radius + 1),
        max(0, center[0] - center_radius) : min(w, center[0] + center_radius + 1),
    ]
    center_ratio = float(center_area.sum() / max(1, pixel_count))

    balance = min(down_ratio, up_ratio) / max(down_ratio, up_ratio, 1e-6)
    score = union_ratio * 0.55 + min(down_ratio, up_ratio) * 0.30 + balance * 0.15
    return score, down_ratio, up_ratio, union_ratio, center_ratio


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
    return int(round(first[0])), int(round(first[1])), int(round(last[0])), int(round(last[1]))


def longest_empty_run(occupied):
    longest = 0
    current = 0
    for value in occupied:
        if value:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def axis_continuity(projections, bins: int):
    bins = max(3, int(bins))
    if len(projections) < 2:
        return 0.0, 1.0, 0.0
    lo = float(np.percentile(projections, 5))
    hi = float(np.percentile(projections, 95))
    if hi <= lo:
        return 0.0, 1.0, 0.0
    clipped = np.clip(projections, lo, hi)
    hist, _edges = np.histogram(clipped, bins=bins, range=(lo, hi))
    occupied = hist > 0
    coverage = float(occupied.mean())
    max_gap_ratio = float(longest_empty_run(occupied) / bins)
    endpoint_score = 0.5 * float(occupied[0]) + 0.5 * float(occupied[-1])
    continuity = coverage * (1.0 - max_gap_ratio) * endpoint_score
    return float(continuity), max_gap_ratio, coverage


def _arm_coverage(values, lo: float, hi: float, *, bins: int = 4) -> float:
    if hi <= lo or len(values) == 0:
        return 0.0
    hist, _edges = np.histogram(np.clip(values, lo, hi), bins=bins, range=(lo, hi))
    return float((hist > 0).mean())


def axial_profile_metrics(points, near_down, near_up, unit_down, unit_up, *, min_dim: int):
    center_band = max(1.5, min_dim * 0.16)
    arm_rows = []
    for prefix, near, unit in (
        ("down", near_down, unit_down),
        ("up", near_up, unit_up),
    ):
        projections = points[near] @ unit
        if len(projections) == 0:
            arm_rows.append((prefix, "neg", 0, 0.0, 0.0))
            arm_rows.append((prefix, "pos", 0, 0.0, 0.0))
            continue

        neg = projections[projections < -center_band]
        pos = projections[projections > center_band]
        neg_extent = float(max(0.0, abs(np.percentile(neg, 5)) - center_band)) if len(neg) else 0.0
        pos_extent = float(max(0.0, np.percentile(pos, 95) - center_band)) if len(pos) else 0.0
        neg_cov = _arm_coverage(-neg, center_band, center_band + neg_extent) if neg_extent > 0 else 0.0
        pos_cov = _arm_coverage(pos, center_band, center_band + pos_extent) if pos_extent > 0 else 0.0
        arm_rows.append((prefix, "neg", int(len(neg)), neg_extent, neg_cov))
        arm_rows.append((prefix, "pos", int(len(pos)), pos_extent, pos_cov))

    arm_pixels = [row[2] for row in arm_rows]
    arm_extents = [row[3] for row in arm_rows]
    arm_coverages = [row[4] for row in arm_rows]
    min_arm_pixels = int(min(arm_pixels)) if arm_pixels else 0
    min_arm_extent_px = float(min(arm_extents)) if arm_extents else 0.0
    min_arm_coverage = float(min(arm_coverages)) if arm_coverages else 0.0

    dist_from_center = np.linalg.norm(points, axis=1)
    center_radius = max(2.0, min_dim * 0.20)
    center_pixels = int((dist_from_center <= center_radius).sum())
    arm_densities = [
        pixels / max(extent, 1e-6)
        for pixels, extent in zip(arm_pixels, arm_extents)
        if pixels > 0 and extent > 0
    ]
    arm_density = float(np.median(arm_densities)) if arm_densities else 0.0
    center_density = center_pixels / max(center_radius * 2.0, 1e-6)
    center_thickness_ratio = center_density / max(arm_density, 1e-6) if arm_density > 0 else 999.0

    return {
        "axis_span_down_px": float(
            np.percentile(points[near_down] @ unit_down, 95) - np.percentile(points[near_down] @ unit_down, 5)
        )
        if near_down.any()
        else 0.0,
        "axis_span_up_px": float(
            np.percentile(points[near_up] @ unit_up, 95) - np.percentile(points[near_up] @ unit_up, 5)
        )
        if near_up.any()
        else 0.0,
        "min_arm_pixels": min_arm_pixels,
        "min_arm_extent_px": min_arm_extent_px,
        "min_arm_coverage": min_arm_coverage,
        "center_pixels": center_pixels,
        "center_thickness_ratio": float(center_thickness_ratio),
        "arm_down_neg_px": arm_rows[0][2],
        "arm_down_pos_px": arm_rows[1][2],
        "arm_up_neg_px": arm_rows[2][2],
        "arm_up_pos_px": arm_rows[3][2],
        "arm_down_neg_cov": arm_rows[0][4],
        "arm_down_pos_cov": arm_rows[1][4],
        "arm_up_neg_cov": arm_rows[2][4],
        "arm_up_pos_cov": arm_rows[3][4],
    }


def estimate_stroke_width(points, near_down, near_up, unit_down, unit_up, normal_down, normal_up, *, min_dim: int):
    widths = []
    center_band = max(1.5, min_dim * 0.16)
    for near, unit, normal in (
        (near_down, unit_down, normal_down),
        (near_up, unit_up, normal_up),
    ):
        projections = points[near] @ unit
        distances = np.abs(points[near] @ normal)
        for sign in (-1, 1):
            side = projections < -center_band if sign < 0 else projections > center_band
            if int(side.sum()) < 3:
                continue
            side_proj = np.abs(projections[side])
            lo = np.percentile(side_proj, 35)
            hi = np.percentile(side_proj, 75)
            mid = side & (np.abs(projections) >= lo) & (np.abs(projections) <= hi)
            if int(mid.sum()) < 3:
                continue
            widths.append(float(np.percentile(distances[mid], 90) * 2.0 + 1.0))
    if not widths:
        return max(1.5, min_dim * 0.22)
    return float(np.clip(np.median(widths), 1.5, max(2.0, min_dim * 0.65)))


def draw_capsule(mask, center, unit, half_length: float, stroke_width: float):
    radius = max(1, int(round(stroke_width / 2.0)))
    thickness = max(1, int(round(stroke_width)))
    p1 = (center[0] - unit[0] * half_length, center[1] - unit[1] * half_length)
    p2 = (center[0] + unit[0] * half_length, center[1] + unit[1] * half_length)
    p1i = (int(round(p1[0])), int(round(p1[1])))
    p2i = (int(round(p2[0])), int(round(p2[1])))
    cv2.line(mask, p1i, p2i, 255, thickness=thickness, lineType=cv2.LINE_AA)
    cv2.circle(mask, p1i, radius, 255, thickness=-1, lineType=cv2.LINE_AA)
    cv2.circle(mask, p2i, radius, 255, thickness=-1, lineType=cv2.LINE_AA)


def rasterize_two_stroke_model(shape, *, center, angle: float, stroke_width: float, half_length_down: float, half_length_up: float):
    h, w = shape
    model = np.zeros((h, w), dtype=np.uint8)
    theta_down = math.radians(angle)
    theta_up = math.radians(180.0 - angle)
    unit_down = np.array([math.cos(theta_down), math.sin(theta_down)], dtype=np.float32)
    unit_up = np.array([math.cos(theta_up), math.sin(theta_up)], dtype=np.float32)
    draw_capsule(model, center, unit_down, half_length_down, stroke_width)
    draw_capsule(model, center, unit_up, half_length_up, stroke_width)
    return model > 0


def distance_fit_errors(component_mask, model_mask, *, center, stroke_width: float):
    component = component_mask > 0
    model = model_mask > 0
    if not component.any() or not model.any():
        return None
    dist_to_model = cv2.distanceTransform((~model).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    dist_to_component = cv2.distanceTransform((~component).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    extra_error = float(dist_to_model[component].mean())
    missing_error = float(dist_to_component[model].mean())

    yy, xx = np.indices(component.shape)
    radius = max(2.0, 1.5 * stroke_width)
    center_region = ((xx - center[0]) ** 2 + (yy - center[1]) ** 2) <= radius * radius
    center_component = component & center_region
    center_extra_error = float(dist_to_model[center_component].mean()) if center_component.any() else 0.0
    return {
        "fit_error": 0.5 * extra_error + 0.5 * missing_error,
        "extra_error": extra_error,
        "missing_error": missing_error,
        "center_extra_error": center_extra_error,
    }


def two_stroke_fit(component_crop, points, axis, profile, *, min_dim: int):
    component_mask = component_crop > 0
    h, w = component_mask.shape
    base_center = np.array([(w - 1) / 2.0, (h - 1) / 2.0], dtype=np.float32)
    normal_down = axis["normal_down"]
    normal_up = axis["normal_up"]
    unit_down = axis["unit_down"]
    unit_up = axis["unit_up"]
    theta_down = math.radians(float(axis["angle"]))
    theta_up = math.radians(float(axis["angle_up"]))

    stroke_width = estimate_stroke_width(
        points,
        np.abs(points @ normal_down) <= max(1.2, min_dim * 0.16),
        np.abs(points @ normal_up) <= max(1.2, min_dim * 0.16),
        unit_down,
        unit_up,
        normal_down,
        normal_up,
        min_dim=min_dim,
    )
    half_down = max(2.0, profile["axis_span_down_px"] / 2.0)
    half_up = max(2.0, profile["axis_span_up_px"] / 2.0)
    best = None
    best_model = None
    for center_dx in (-1.0, 0.0, 1.0):
        for center_dy in (-1.0, 0.0, 1.0):
            center = base_center + np.array([center_dx, center_dy], dtype=np.float32)
            for angle_delta in (-1.0, 0.0, 1.0):
                angle = float(axis["angle"] + angle_delta)
                if not (42.0 <= angle <= 47.0):
                    continue
                for width_factor in (0.85, 1.0, 1.15):
                    width = max(1.5, stroke_width * width_factor)
                    for len_factor in (0.9, 1.0, 1.1):
                        model = rasterize_two_stroke_model(
                            component_mask.shape,
                            center=center,
                            angle=angle,
                            stroke_width=width,
                            half_length_down=half_down * len_factor,
                            half_length_up=half_up * len_factor,
                        )
                        errors = distance_fit_errors(component_mask, model, center=center, stroke_width=width)
                        if errors is None:
                            continue
                        if best is None or errors["fit_error"] < best["fit_error"]:
                            best = {
                                **errors,
                                "stroke_width": float(width),
                                "model_center_x": float(center[0]),
                                "model_center_y": float(center[1]),
                                "model_angle": float(angle),
                            }
                            best_model = model
    if best is None:
        return {
            "fit_error": 999.0,
            "extra_error": 999.0,
            "missing_error": 999.0,
            "center_extra_error": 999.0,
            "stroke_width": float(stroke_width),
        }, None
    return best, best_model


def narrow_corridor_metrics(points, normal_down, normal_up, *, min_dim: int):
    tolerance = max(0.75, min_dim * 0.08)
    near_down = np.abs(points @ normal_down) <= tolerance
    near_up = np.abs(points @ normal_up) <= tolerance
    union = near_down | near_up
    union_ratio = float(union.sum() / max(1, len(points)))

    overlap = near_down & near_up
    assigned_down = near_down & (np.abs(points @ normal_down) <= np.abs(points @ normal_up))
    assigned_up = near_up & (np.abs(points @ normal_up) < np.abs(points @ normal_down))
    count_down = max(int(assigned_down.sum()), int(overlap.sum()))
    count_up = max(int(assigned_up.sum()), int(overlap.sum()))
    balance = min(count_down, count_up) / max(count_down, count_up, 1)
    return {
        "axis_core_union": union_ratio,
        "axis_core_balance": float(balance),
    }


def fit_cross_axes_fast(mask, args, *, offset=(0, 0)):
    ys, xs = np.where(mask > 0)
    if len(xs) < 6:
        return None
    x, y, w, h = int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
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
    if centroid_offset > args.max_center_offset:
        return None

    tolerance = max(1.2, min_dim * 0.16)
    best = None
    for axis in args._axis_cache:
        angle = axis["angle"]
        angle_up = axis["angle_up"]
        angle_delta = axis["angle_delta"]
        normal_down = axis["normal_down"]
        normal_up = axis["normal_up"]
        unit_down = axis["unit_down"]
        unit_up = axis["unit_up"]

        dist_down = np.abs(points @ normal_down)
        dist_up = np.abs(points @ normal_up)
        near_down = dist_down <= tolerance
        near_up = dist_up <= tolerance
        union = near_down | near_up
        union_ratio = float(union.sum() / len(points))
        if union_ratio < args.min_axis_union:
            continue

        assigned_down = near_down & (dist_down <= dist_up)
        assigned_up = near_up & (dist_up < dist_down)
        overlap = near_down & near_up
        count_down = max(int(assigned_down.sum()), int(overlap.sum()))
        count_up = max(int(assigned_up.sum()), int(overlap.sum()))
        if count_down == 0 or count_up == 0:
            continue
        balance = min(count_down, count_up) / max(count_down, count_up)
        if balance < args.min_axis_balance:
            continue

        proj_down = points[near_down] @ unit_down
        proj_up = points[near_up] @ unit_up
        extent_down = float(np.percentile(proj_down, 95) - np.percentile(proj_down, 5)) if len(proj_down) else 0.0
        extent_up = float(np.percentile(proj_up, 95) - np.percentile(proj_up, 5)) if len(proj_up) else 0.0
        length_ratio = min(extent_down, extent_up) / max(extent_down, extent_up, 1e-6)
        if length_ratio < args.min_length_ratio:
            continue
        continuity_down, gap_down, coverage_down = axis_continuity(proj_down, args.continuity_bins)
        continuity_up, gap_up, coverage_up = axis_continuity(proj_up, args.continuity_bins)
        continuity = min(continuity_down, continuity_up)
        max_gap_ratio = max(gap_down, gap_up)
        continuity_coverage = min(coverage_down, coverage_up)
        if continuity < args.min_continuity:
            continue
        if max_gap_ratio > args.max_gap_ratio:
            continue
        profile = axial_profile_metrics(
            points,
            near_down,
            near_up,
            unit_down,
            unit_up,
            min_dim=min_dim,
        )
        core_profile = narrow_corridor_metrics(
            points,
            normal_down,
            normal_up,
            min_dim=min_dim,
        )
        if args.two_stroke_fit:
            two_stroke_profile, _model_mask = two_stroke_fit(crop, points, axis, profile, min_dim=min_dim)
        else:
            two_stroke_profile = {
                "fit_error": 0.0,
                "extra_error": 0.0,
                "missing_error": 0.0,
                "center_extra_error": 0.0,
                "stroke_width": 0.0,
            }
        min_axis_span_px = min(profile["axis_span_down_px"], profile["axis_span_up_px"])
        if min_axis_span_px < args.min_axis_span_px:
            continue
        if profile["min_arm_extent_px"] < args.min_arm_extent_px:
            continue
        if profile["min_arm_coverage"] < args.min_arm_coverage:
            continue
        if profile["center_thickness_ratio"] > args.max_center_thickness_ratio:
            continue
        if core_profile["axis_core_union"] < args.min_axis_core_union:
            continue
        if core_profile["axis_core_balance"] < args.min_axis_core_balance:
            continue

        orth_delta = 0.0
        if angle_delta > args.max_angle_delta or orth_delta > args.max_orth_delta:
            continue

        angle_score = max(0.0, 1.0 - angle_delta / max(args.max_angle_delta, 1e-6))
        center_score = max(0.0, 1.0 - centroid_offset / max(args.max_center_offset, 1e-6))
        weight_total = (
            args.weight_axis_union
            + args.weight_axis_balance
            + args.weight_length_ratio
            + args.weight_angle
            + args.weight_center
            + args.weight_continuity
        )
        score = (
            union_ratio * args.weight_axis_union
            + balance * args.weight_axis_balance
            + length_ratio * args.weight_length_ratio
            + angle_score * args.weight_angle
            + center_score * args.weight_center
            + continuity * args.weight_continuity
        ) / max(weight_total, 1e-6)
        if score < args.min_score:
            continue
        down_line = line_segment_through_box(w, h, float(angle))
        up_line = line_segment_through_box(w, h, angle_up)
        base_x = offset[0] + x
        base_y = offset[1] + y
        candidate = {
            "score": float(score),
            "method": "axis",
            "bbox": (base_x, base_y, w, h),
            "line_down": tuple(v + (base_x if i % 2 == 0 else base_y) for i, v in enumerate(down_line)),
            "line_up": tuple(v + (base_x if i % 2 == 0 else base_y) for i, v in enumerate(up_line)),
            "angle_down": float(angle),
            "angle_up": angle_up,
            "angle_delta": angle_delta,
            "orth_delta": orth_delta,
            "length_ratio": float(length_ratio),
            "center_offset": centroid_offset,
            "fill": float((crop > 0).sum() / max(1, w * h)),
            "axis_union": union_ratio,
            "axis_balance": float(balance),
            "continuity": float(continuity),
            "max_gap_ratio": float(max_gap_ratio),
            "continuity_coverage": float(continuity_coverage),
            **profile,
            **core_profile,
            **two_stroke_profile,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def find_x_candidates(
    hsv_roi,
    *,
    gate,
    args,
):
    mask = mask_from_hsv(hsv_roi, gate)
    roi_h, roi_w = mask.shape[:2]
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    rows = []
    for label in range(1, count):
        x, y, bw, bh, area = stats[label]
        if area < 6:
            continue
        if bw < args.min_size or bh < args.min_size or bw > args.max_size or bh > args.max_size:
            continue
        aspect = bw / max(1, bh)
        if aspect < args.min_aspect or aspect > args.max_aspect:
            continue
        center_x_ratio = (x + bw / 2.0) / max(1, roi_w)
        center_y_ratio = (y + bh / 2.0) / max(1, roi_h)
        if center_x_ratio < args.min_x_ratio or center_x_ratio > args.max_x_ratio:
            continue
        if center_y_ratio < args.min_y_ratio or center_y_ratio > args.max_y_ratio:
            continue
        fill = area / max(1, bw * bh)
        if fill < args.min_fill or fill > args.max_fill:
            continue
        component_crop = np.where(labels[y : y + bh, x : x + bw] == label, 255, 0).astype(np.uint8)
        prefilter = diagonal_score(component_crop)
        if prefilter is None:
            continue
        pre_score, pre_down, pre_up, pre_union, _pre_center = prefilter
        if pre_score < args.prefilter_min_score:
            continue
        if min(pre_down, pre_up) < args.prefilter_min_diag_each:
            continue
        if pre_union < args.prefilter_min_union:
            continue
        result = fit_cross_axes_fast(component_crop, args, offset=(int(x), int(y)))
        if result is None:
            continue
        x, y, bw, bh = result["bbox"]
        result = dict(result)
        result["gate"] = gate.name
        result["mode"] = gate.mode
        result["box"] = result["bbox"]
        rows.append(result)
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


def scan_one(path: Path, args):
    if args.opencv_threads > 0:
        cv2.setNumThreads(args.opencv_threads)
    image = read_bgr(path)
    if image is None:
        return []
    h, _w = image.shape[:2]
    roi_h = int(h * args.roi_top_ratio)
    hsv_roi = cv2.cvtColor(image[:roi_h, :], cv2.COLOR_BGR2HSV)
    rows = []
    gate_names = set(args.gates)
    for gate in GATES:
        if gate.name not in gate_names:
            continue
        rows.extend(find_x_candidates(hsv_roi, gate=gate, args=args))
    if not rows:
        return []
    rows.sort(key=lambda row: row["score"], reverse=True)
    best = []
    min_distance_sq = args.dedupe_distance * args.dedupe_distance
    for row in rows:
        x, y, w, h = row["box"]
        center = (x + w // 2, y + h // 2)
        if any(
            (center[0] - existing["_center"][0]) ** 2 + (center[1] - existing["_center"][1]) ** 2
            < min_distance_sq
            for existing in best
        ):
            continue
        row["_center"] = center
        best.append(row)
        if len(best) >= args.max_per_image:
            break
    for row in best:
        row["path"] = path
        row.pop("_center", None)
    return best


def paint_points(crop, mask, color):
    if not np.any(mask):
        return
    point_mask = mask.astype(np.uint8) * 255
    point_mask = cv2.dilate(point_mask, np.ones((3, 3), np.uint8), iterations=1)
    color_layer = np.full_like(crop, color)
    crop[point_mask > 0] = (crop[point_mask > 0] * 0.30 + color_layer[point_mask > 0] * 0.70).astype(np.uint8)


def draw_match_debug(crop, image, row, *, x0: int, y0: int, roi_top_ratio: float):
    gate = gate_by_name(row["gate"])
    if gate is None:
        return crop
    h, _w = image.shape[:2]
    roi_h = int(h * roi_top_ratio)
    if roi_h <= 0:
        return crop
    hsv_roi = cv2.cvtColor(image[:roi_h, :], cv2.COLOR_BGR2HSV)
    mask = mask_from_hsv(hsv_roi, gate)
    x, y, bw, bh = row["box"]
    if y < 0 or x < 0 or y + bh > mask.shape[0] or x + bw > mask.shape[1]:
        return crop

    mask_crop = mask[y : y + bh, x : x + bw] > 0
    ys, xs = np.where(mask_crop)
    if len(xs) == 0:
        return crop

    points = np.column_stack(
        (
            xs.astype(np.float32) - (bw - 1) / 2.0,
            ys.astype(np.float32) - (bh - 1) / 2.0,
        )
    )
    tolerance = max(1.2, min(bw, bh) * 0.16)
    theta_down = math.radians(float(row["angle_down"]))
    theta_up = math.radians(float(row["angle_up"]))
    normal_down = np.array([-math.sin(theta_down), math.cos(theta_down)], dtype=np.float32)
    normal_up = np.array([-math.sin(theta_up), math.cos(theta_up)], dtype=np.float32)
    near_down = np.abs(points @ normal_down) <= tolerance
    near_up = np.abs(points @ normal_up) <= tolerance

    local_masks = {
        "down": np.zeros(crop.shape[:2], dtype=bool),
        "up": np.zeros(crop.shape[:2], dtype=bool),
        "both": np.zeros(crop.shape[:2], dtype=bool),
        "off": np.zeros(crop.shape[:2], dtype=bool),
    }
    gx = x + xs - x0
    gy = y + ys - y0
    in_crop = (gx >= 0) & (gy >= 0) & (gx < crop.shape[1]) & (gy < crop.shape[0])
    for name, selector in (
        ("down", near_down & ~near_up),
        ("up", near_up & ~near_down),
        ("both", near_down & near_up),
        ("off", ~(near_down | near_up)),
    ):
        selected = selector & in_crop
        local_masks[name][gy[selected], gx[selected]] = True

    paint_points(crop, local_masks["off"], (0, 128, 255))
    paint_points(crop, local_masks["down"], (0, 255, 255))
    paint_points(crop, local_masks["up"], (255, 255, 0))
    paint_points(crop, local_masks["both"], (255, 255, 255))

    down = row.get("line_down")
    up = row.get("line_up")
    if down is None:
        local_down = line_segment_through_box(bw, bh, float(row["angle_down"]))
        down = tuple(v + (x if i % 2 == 0 else y) for i, v in enumerate(local_down))
    if up is None:
        local_up = line_segment_through_box(bw, bh, float(row["angle_up"]))
        up = tuple(v + (x if i % 2 == 0 else y) for i, v in enumerate(local_up))
    if down:
        cv2.line(crop, (down[0] - x0, down[1] - y0), (down[2] - x0, down[3] - y0), (0, 220, 255), 1, cv2.LINE_AA)
    if up:
        cv2.line(crop, (up[0] - x0, up[1] - y0), (up[2] - x0, up[3] - y0), (255, 220, 0), 1, cv2.LINE_AA)
    return crop


def make_sheet(rows, output_path: Path, *, max_items: int, roi_top_ratio: float, debug_overlay: bool = False) -> None:
    tiles = []
    for row in rows[:max_items]:
        img = read_bgr(row["path"])
        if img is None:
            continue
        h, w = img.shape[:2]
        x, y, bw, bh = row["box"]
        pad = 45
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(int(h * roi_top_ratio), y + bh + pad)
        crop = img[y0:y1, x0:x1].copy()
        if debug_overlay:
            crop = draw_match_debug(crop, img, row, x0=x0, y0=y0, roi_top_ratio=roi_top_ratio)
        cv2.rectangle(crop, (x - x0, y - y0), (x - x0 + bw, y - y0 + bh), (0, 0, 255), 2)
        tile = cv2.resize(crop, (180, 120), interpolation=cv2.INTER_AREA)
        tile = cv2.copyMakeBorder(tile, 62, 32, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(
            tile,
            f"score={row['score']:.3f} {row['gate']}",
            (8, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.39,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            f"u={row['axis_union']:.3f} b={row['axis_balance']:.2f} l={row['length_ratio']:.2f} f={row['fill']:.2f}",
            (8, 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            f"cont={row.get('continuity', 0.0):.2f} gap={row.get('max_gap_ratio', 0.0):.2f} c={row['center_offset']:.2f}",
            (8, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            f"span={min(row.get('axis_span_down_px', 0.0), row.get('axis_span_up_px', 0.0)):.1f} arm={row.get('min_arm_extent_px', 0.0):.1f} core={row.get('axis_core_union', 0.0):.2f}",
            (8, 72),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.34,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            row["path"].parent.name[:32],
            (8, 166),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.34,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        tiles.append(tile)
    if not tiles:
        return
    cols = 5
    blank = np.full_like(tiles[0], 255)
    while len(tiles) % cols:
        tiles.append(blank.copy())
    sheet = np.vstack([np.hstack(tiles[i : i + cols]) for i in range(0, len(tiles), cols)])
    write_png(output_path, sheet)


def run_threaded(paths, args):
    worker_count = args.workers
    if worker_count <= 0:
        worker_count = min(8, max(1, (os.cpu_count() or 4) - 1))
    if args.opencv_threads > 0:
        cv2.setNumThreads(args.opencv_threads)

    rows = []
    completed = 0
    next_index = 0
    in_flight_limit = max(worker_count, worker_count * 2)
    executor_class = ProcessPoolExecutor if args.backend == "process" else ThreadPoolExecutor
    progress_interval = max(1, args.progress_interval)
    print(f"workers: {worker_count}; backend: {args.backend}; opencv_threads: {cv2.getNumThreads()}")

    def submit_more(executor, futures):
        nonlocal next_index
        while next_index < len(paths) and len(futures) < in_flight_limit:
            path = paths[next_index]
            next_index += 1
            futures.add(executor.submit(scan_one, path, args))

    with executor_class(max_workers=worker_count) as executor:
        futures = set()
        submit_more(executor, futures)
        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                rows.extend(future.result())
                completed += 1
                if completed % progress_interval == 0:
                    print(f"scanned {completed}/{len(paths)}; hits={len(rows)}")
            submit_more(executor, futures)
    return rows, completed


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan screenshots for geometric X close candidates.")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="strict")
    parser.add_argument("--log-dir", type=Path, default=Path("log"))
    parser.add_argument("--output-dir", type=Path, default=Path("ads2/assets/review_crops/x_geometry_scan"))
    parser.add_argument("--roi-top-ratio", type=float, default=0.40)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--backend", choices=["thread", "process"], default="thread")
    parser.add_argument("--opencv-threads", type=int, default=1)
    parser.add_argument("--progress-interval", type=int, default=250)
    parser.add_argument("--sheet-items", type=int, default=100)
    parser.add_argument("--debug-sheet", action="store_true")
    parser.add_argument("--max-per-image", type=int, default=2)
    parser.add_argument("--dedupe-distance", type=int, default=8)

    parser.add_argument(
        "--gates",
        nargs="*",
        default=["white_strict", "white_soft", "black_strict", "black_soft"],
        help="Color gates to test. Available: " + ", ".join(gate.name for gate in GATES),
    )

    parser.add_argument("--min-size", type=int, default=10)
    parser.add_argument("--max-size", type=int, default=40)
    parser.add_argument("--min-aspect", type=float, default=0.75)
    parser.add_argument("--max-aspect", type=float, default=1.35)
    parser.add_argument("--min-fill", type=float, default=0.18)
    parser.add_argument("--max-fill", type=float, default=1.00)
    parser.add_argument("--min-x-ratio", type=float, default=0.0)
    parser.add_argument("--max-x-ratio", type=float, default=1.0)
    parser.add_argument("--min-y-ratio", type=float, default=0.0)
    parser.add_argument("--max-y-ratio", type=float, default=1.0)
    parser.add_argument("--min-score", type=float, default=0.85)
    parser.add_argument("--angle-down-min", type=float, default=42.0)
    parser.add_argument("--angle-down-max", type=float, default=47.0)
    parser.add_argument("--angle-up-min", type=float, default=133.0)
    parser.add_argument("--angle-up-max", type=float, default=138.0)
    parser.add_argument("--angle-step", type=float, default=0.5)
    parser.add_argument("--max-angle-delta", type=float, default=3.0)
    parser.add_argument("--max-orth-delta", type=float, default=2.0)
    parser.add_argument("--min-length-ratio", type=float, default=0.88)
    parser.add_argument("--max-center-offset", type=float, default=0.17)
    parser.add_argument("--min-axis-union", type=float, default=0.55)
    parser.add_argument("--min-axis-balance", type=float, default=0.35)
    parser.add_argument("--continuity-bins", type=int, default=7)
    parser.add_argument("--min-continuity", type=float, default=0.0)
    parser.add_argument("--max-gap-ratio", type=float, default=1.0)
    parser.add_argument("--min-axis-span-px", type=float, default=0.0)
    parser.add_argument("--min-arm-extent-px", type=float, default=0.0)
    parser.add_argument("--min-arm-coverage", type=float, default=0.0)
    parser.add_argument("--max-center-thickness-ratio", type=float, default=999.0)
    parser.add_argument("--min-axis-core-union", type=float, default=0.0)
    parser.add_argument("--min-axis-core-balance", type=float, default=0.0)
    parser.add_argument("--two-stroke-fit", action="store_true")
    parser.add_argument("--weight-axis-union", type=float, default=0.30)
    parser.add_argument("--weight-axis-balance", type=float, default=0.22)
    parser.add_argument("--weight-length-ratio", type=float, default=0.23)
    parser.add_argument("--weight-angle", type=float, default=0.15)
    parser.add_argument("--weight-center", type=float, default=0.10)
    parser.add_argument("--weight-continuity", type=float, default=0.0)
    parser.add_argument("--prefilter-min-score", type=float, default=0.75)
    parser.add_argument("--prefilter-min-diag-each", type=float, default=0.40)
    parser.add_argument("--prefilter-min-union", type=float, default=0.80)
    args = parser.parse_args()
    apply_preset(args, provided_cli_options(sys.argv[1:]))
    args._axis_cache = build_axis_cache(args)
    if not args._axis_cache:
        raise SystemExit("No angle candidates left after applying angle filters.")
    known_gates = {gate.name for gate in GATES}
    unknown_gates = [name for name in args.gates if name not in known_gates]
    if unknown_gates:
        raise SystemExit(f"Unknown gate(s): {', '.join(unknown_gates)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(args.log_dir.rglob("*.png"))
    if args.limit > 0:
        paths = paths[: args.limit]

    rows, completed = run_threaded(paths, args)
    rows.sort(key=lambda row: row["score"], reverse=True)

    report_lines = [
        "# X geometry scan",
        "",
        f"Images selected: {len(paths)}",
        f"Images completed: {completed}",
        f"Hits: {len(rows)}",
        f"Hit screens: {len({row['path'] for row in rows})}",
        f"Preset: {args.preset}",
        f"Backend: {args.backend}",
        f"Debug sheet: {args.debug_sheet}",
        f"ROI: top {args.roi_top_ratio:.0%}",
        f"Gates: {', '.join(args.gates)}",
        f"Filters: min_score={args.min_score}, angle_down={args.angle_down_min}..{args.angle_down_max}, angle_up={args.angle_up_min}..{args.angle_up_max}",
        f"Position: x_ratio={args.min_x_ratio}..{args.max_x_ratio}, y_ratio={args.min_y_ratio}..{args.max_y_ratio}",
        f"Filters: max_angle_delta={args.max_angle_delta}, max_orth_delta={args.max_orth_delta}, min_length_ratio={args.min_length_ratio}, max_center_offset={args.max_center_offset}",
        f"Axis filters: angle_step={args.angle_step}, min_axis_union={args.min_axis_union}, min_axis_balance={args.min_axis_balance}",
        f"Continuity: bins={args.continuity_bins}, min_continuity={args.min_continuity}, max_gap_ratio={args.max_gap_ratio}",
        f"Profile filters: min_axis_span_px={args.min_axis_span_px}, min_arm_extent_px={args.min_arm_extent_px}, min_arm_coverage={args.min_arm_coverage}, max_center_thickness_ratio={args.max_center_thickness_ratio}, min_axis_core_union={args.min_axis_core_union}, min_axis_core_balance={args.min_axis_core_balance}",
        f"Two-stroke fit: {args.two_stroke_fit}",
        f"Score weights: union={args.weight_axis_union}, balance={args.weight_axis_balance}, length={args.weight_length_ratio}, angle={args.weight_angle}, center={args.weight_center}, continuity={args.weight_continuity}",
        f"Prefilter: min_score={args.prefilter_min_score}, min_diag_each={args.prefilter_min_diag_each}, min_union={args.prefilter_min_union}",
        "",
        "| score | method | gate | box | angle_down | angle_up | length_ratio | center_offset | axis_union | axis_balance | fill | continuity | max_gap | span_down | span_up | min_arm_px | min_arm_extent | min_arm_cov | center_px | center_thick | core_union | core_balance | fit_error | extra_error | missing_error | center_extra_error | stroke_width | file |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        report_lines.append(
            f"| {row['score']:.3f} | {row['method']} | {row['gate']} | `{row['box']}` | "
            f"{row['angle_down']:.2f} | {row['angle_up']:.2f} | "
            f"{row['length_ratio']:.3f} | {row['center_offset']:.3f} | "
            f"{row['axis_union']:.3f} | {row['axis_balance']:.3f} | {row['fill']:.3f} | "
            f"{row.get('continuity', 0.0):.3f} | {row.get('max_gap_ratio', 0.0):.3f} | "
            f"{row.get('axis_span_down_px', 0.0):.2f} | {row.get('axis_span_up_px', 0.0):.2f} | "
            f"{row.get('min_arm_pixels', 0)} | {row.get('min_arm_extent_px', 0.0):.2f} | "
            f"{row.get('min_arm_coverage', 0.0):.3f} | {row.get('center_pixels', 0)} | "
            f"{row.get('center_thickness_ratio', 0.0):.3f} | "
            f"{row.get('axis_core_union', 0.0):.3f} | {row.get('axis_core_balance', 0.0):.3f} | "
            f"{row.get('fit_error', 0.0):.3f} | {row.get('extra_error', 0.0):.3f} | "
            f"{row.get('missing_error', 0.0):.3f} | {row.get('center_extra_error', 0.0):.3f} | "
            f"{row.get('stroke_width', 0.0):.2f} | "
            f"`{row['path'].as_posix()}` |"
        )
    (args.output_dir / "scan_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    make_sheet(rows, args.output_dir / "hits_top100.png", max_items=args.sheet_items, roi_top_ratio=args.roi_top_ratio)
    if args.debug_sheet:
        make_sheet(
            rows,
            args.output_dir / "hits_debug_top100.png",
            max_items=args.sheet_items,
            roi_top_ratio=args.roi_top_ratio,
            debug_overlay=True,
        )

    print(args.output_dir.resolve())
    print("report:", (args.output_dir / "scan_report.md").resolve())
    print("sheet:", (args.output_dir / "hits_top100.png").resolve())
    if args.debug_sheet:
        print("debug sheet:", (args.output_dir / "hits_debug_top100.png").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
