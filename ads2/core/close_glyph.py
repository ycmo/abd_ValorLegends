from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

import src.vision_matcher as vm
from src.vision_matcher import MatchResult, Roi


@dataclass(frozen=True)
class CloseGlyphSpec:
    name: str
    source_name: str
    threshold: float = 0.60
    scales: Tuple[float, ...] = (0.95, 1.0, 1.1)
    padding: int = 12
    saturation_max: int = 30
    value_min: int = 230


DEFAULT_CLOSE_GLYPHS: Tuple[CloseGlyphSpec, ...] = (
    CloseGlyphSpec(name="glyph_skip_next", source_name="skip_next_edge.png"),
    CloseGlyphSpec(
        name="glyph_google_play_pill",
        source_name="google_play_pill_edge.png",
        threshold=0.50,
        saturation_max=40,
        value_min=180,
    ),
    CloseGlyphSpec(
        name="glyph_skip_next_text",
        source_name="skip_next_text_edge.png",
        threshold=0.50,
        saturation_max=40,
        value_min=180,
    ),
)


def is_close_glyph_match(result: Optional[MatchResult]) -> bool:
    return bool(result and result.template_path.name.startswith("__glyph_"))


def match_close_glyphs(
    screen: np.ndarray,
    close_glyphs_dir: Path,
    *,
    roi: Optional[Roi] = None,
    specs: Sequence[CloseGlyphSpec] = DEFAULT_CLOSE_GLYPHS,
) -> Optional[MatchResult]:
    best: Optional[MatchResult] = None
    for spec in specs:
        template = _read_edge_template(close_glyphs_dir / spec.source_name)
        if template is None:
            continue
        result = _match_one(screen, template, spec, roi=roi)
        if result is None:
            continue
        if best is None or result.confidence > best.confidence:
            best = MatchResult(
                template_path=Path(f"__glyph_{spec.name}.png"),
                confidence=result.confidence,
                center=result.center,
                bbox=result.bbox,
                brightness_ratio=None,
            )
    return best


def _match_one(
    screen: np.ndarray,
    template: np.ndarray,
    spec: CloseGlyphSpec,
    *,
    roi: Optional[Roi],
) -> Optional[MatchResult]:
    haystack, offset = _crop(screen, roi)
    if haystack.size == 0:
        return None

    edge = _color_edge_from_bgr(haystack, saturation_max=spec.saturation_max, value_min=spec.value_min)
    best_score = 0.0
    best_box = None
    for scale in spec.scales:
        tw = max(4, int(round(template.shape[1] * scale)))
        th = max(4, int(round(template.shape[0] * scale)))
        if tw > edge.shape[1] or th > edge.shape[0]:
            continue
        resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_NEAREST)
        result = cv2.matchTemplate(edge, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if float(score) > best_score:
            best_score = float(score)
            best_box = (int(loc[0] + offset[0]), int(loc[1] + offset[1]), tw, th)

    if best_box is None or best_score < spec.threshold:
        return None

    x, y, w, h = best_box
    return MatchResult(
        template_path=Path(f"__glyph_{spec.name}.png"),
        confidence=best_score,
        center=(x + w // 2, y + h // 2),
        bbox=best_box,
        brightness_ratio=None,
    )


@lru_cache(maxsize=16)
def _build_template(source_path: Path, spec: CloseGlyphSpec) -> Optional[np.ndarray]:
    try:
        source = _read_bgr(source_path)
    except Exception:
        return None
    padded = cv2.copyMakeBorder(
        source,
        spec.padding,
        spec.padding,
        spec.padding,
        spec.padding,
        cv2.BORDER_REPLICATE,
    )
    edge = _color_edge_from_bgr(padded, saturation_max=spec.saturation_max, value_min=spec.value_min)
    bbox = _bbox_from_mask(edge)
    if bbox is None:
        return None
    return _crop_bbox(edge, bbox, pad=1)


@lru_cache(maxsize=16)
def _read_edge_template(source_path: Path) -> Optional[np.ndarray]:
    try:
        raw = vm.read_image(source_path, cv2.IMREAD_GRAYSCALE)
    except Exception:
        return None
    if raw.ndim == 3:
        raw = cv2.cvtColor(raw[:, :, :3], cv2.COLOR_BGR2GRAY)
    return cv2.threshold(raw, 1, 255, cv2.THRESH_BINARY)[1]


def _read_bgr(path: Path) -> np.ndarray:
    raw = vm.read_image(path, cv2.IMREAD_UNCHANGED)
    if raw.ndim == 2:
        return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    return raw[:, :, :3]


def _color_edge_from_bgr(bgr: np.ndarray, *, saturation_max: int, value_min: int) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] <= saturation_max) & (hsv[:, :, 2] >= value_min)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    edge = cv2.Canny(mask, 40, 120)
    return cv2.dilate(edge, np.ones((2, 2), np.uint8), iterations=1)


def _bbox_from_mask(mask: np.ndarray):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def _crop_bbox(image: np.ndarray, bbox, *, pad: int) -> np.ndarray:
    h, w = image.shape[:2]
    x, y, bw, bh = bbox
    return image[
        max(0, y - pad) : min(h, y + bh + pad),
        max(0, x - pad) : min(w, x + bw + pad),
    ]


def _crop(screen: np.ndarray, roi: Optional[Roi]):
    if roi is None:
        return screen, (0, 0)
    x, y, w, h = roi
    height, width = screen.shape[:2]
    x1 = max(0, int(x))
    y1 = max(0, int(y))
    x2 = min(width, x1 + max(0, int(w)))
    y2 = min(height, y1 + max(0, int(h)))
    return screen[y1:y2, x1:x2], (x1, y1)
