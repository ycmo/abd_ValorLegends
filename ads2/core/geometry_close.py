from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

from src.vision_matcher import MatchResult, Roi
from ads2.tools.calibrate_x_geometry_rules import GATES
from ads2.tools.scan_x_geometry_candidates import build_axis_cache, find_x_candidates


GEOMETRY_CLOSE_PATH = Path("__geometry_close.png")


@dataclass(frozen=True)
class GeometryCloseSpec:
    threshold: float = 0.85
    roi_top_ratio: float = 0.40
    max_results: int = 1
    min_size: int = 10
    max_size: int = 52
    min_aspect: float = 0.65
    max_aspect: float = 1.55
    min_fill: float = 0.18
    max_fill: float = 0.55
    min_axis_union: float = 0.75
    min_axis_balance: float = 0.35
    min_length_ratio: float = 0.88
    max_center_offset: float = 0.17
    min_continuity: float = 0.0
    max_gap_ratio: float = 1.0
    gates: Tuple[str, ...] = ("white_strict", "white_soft", "black_strict", "black_soft")


def is_geometry_close_match(result: Optional[MatchResult]) -> bool:
    return bool(result and result.template_path.name == GEOMETRY_CLOSE_PATH.name)


def match_geometry_close(
    screen: np.ndarray,
    *,
    roi: Optional[Roi] = None,
    spec: GeometryCloseSpec = GeometryCloseSpec(),
) -> Optional[MatchResult]:
    matches = match_geometry_close_all(screen, roi=roi, spec=spec)
    return matches[0] if matches else None


def match_geometry_close_all(
    screen: np.ndarray,
    *,
    roi: Optional[Roi] = None,
    spec: GeometryCloseSpec = GeometryCloseSpec(),
) -> Sequence[MatchResult]:
    haystack, offset = _crop(screen, roi, spec.roi_top_ratio)
    if haystack.size == 0:
        return []

    args = _build_args(spec)
    hsv = cv2.cvtColor(haystack, cv2.COLOR_BGR2HSV)
    gate_names = set(spec.gates)
    rows = []
    for gate in GATES:
        if gate.name not in gate_names:
            continue
        rows.extend(find_x_candidates(hsv, gate=gate, args=args))

    if not rows:
        return []

    rows.sort(key=lambda row: row["score"], reverse=True)
    matches = []
    min_distance_sq = 16 * 16
    for row in rows:
        if row["score"] < spec.threshold:
            continue
        x, y, w, h = row["box"]
        abs_box = (int(x + offset[0]), int(y + offset[1]), int(w), int(h))
        center = (abs_box[0] + abs_box[2] // 2, abs_box[1] + abs_box[3] // 2)
        if any(
            (center[0] - existing.center[0]) ** 2 + (center[1] - existing.center[1]) ** 2 < min_distance_sq
            for existing in matches
        ):
            continue
        matches.append(
            MatchResult(
                template_path=GEOMETRY_CLOSE_PATH,
                confidence=float(row["score"]),
                center=center,
                bbox=abs_box,
                brightness_ratio=None,
            )
        )
        if len(matches) >= spec.max_results:
            break
    return matches


def _build_args(spec: GeometryCloseSpec):
    args = SimpleNamespace(
        min_size=spec.min_size,
        max_size=spec.max_size,
        min_aspect=spec.min_aspect,
        max_aspect=spec.max_aspect,
        min_fill=spec.min_fill,
        max_fill=spec.max_fill,
        min_x_ratio=0.0,
        max_x_ratio=1.0,
        min_y_ratio=0.0,
        max_y_ratio=1.0,
        min_score=spec.threshold,
        angle_down_min=42.0,
        angle_down_max=47.0,
        angle_up_min=133.0,
        angle_up_max=138.0,
        angle_step=0.5,
        max_angle_delta=3.0,
        max_orth_delta=2.0,
        min_length_ratio=spec.min_length_ratio,
        max_center_offset=spec.max_center_offset,
        min_axis_union=spec.min_axis_union,
        min_axis_balance=spec.min_axis_balance,
        continuity_bins=7,
        min_continuity=spec.min_continuity,
        max_gap_ratio=spec.max_gap_ratio,
        weight_axis_union=0.30,
        weight_axis_balance=0.22,
        weight_length_ratio=0.23,
        weight_angle=0.15,
        weight_center=0.10,
        weight_continuity=0.0,
        prefilter_min_score=0.45,
        prefilter_min_diag_each=0.20,
        prefilter_min_union=0.45,
    )
    args._axis_cache = build_axis_cache(args)
    return args


def _crop(screen: np.ndarray, roi: Optional[Roi], roi_top_ratio: float):
    h, w = screen.shape[:2]
    if roi is None:
        y2 = max(1, int(h * roi_top_ratio))
        return screen[:y2, :], (0, 0)
    x, y, rw, rh = roi
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w, x + rw)
    y2 = min(h, y + rh)
    return screen[y1:y2, x1:x2], (x1, y1)
