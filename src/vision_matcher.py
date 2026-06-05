from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.config import MATCH_THRESHOLD

Roi = Tuple[int, int, int, int]  # x, y, width, height


@dataclass(frozen=True)
class MatchResult:
    template_path: Path
    confidence: float
    center: Tuple[int, int]
    bbox: Roi

    @property
    def x(self) -> int:
        return self.center[0]

    @property
    def y(self) -> int:
        return self.center[1]


def read_image(path: Path, flags: int = cv2.IMREAD_UNCHANGED) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, flags)
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    path.write_bytes(buf.tobytes())
    return path


def roi_from_ratio(screen: np.ndarray, ratio: Tuple[float, float, float, float]) -> Roi:
    x1r, y1r, x2r, y2r = ratio
    height, width = screen.shape[:2]
    x = int(width * x1r)
    y = int(height * y1r)
    return (x, y, int(width * x2r) - x, int(height * y2r) - y)


class VisionMatcher:
    """OpenCV template matcher with unicode-path image loading and ROI support."""

    def __init__(self, threshold: float = MATCH_THRESHOLD, debug_dir: Optional[Path] = None):
        self.threshold = threshold
        self.debug_dir = debug_dir

    def match_template(
        self,
        screen: np.ndarray,
        template_path: Path,
        threshold: Optional[float] = None,
        roi: Optional[Roi] = None,
    ) -> Optional[MatchResult]:
        if not template_path.exists():
            return None

        template_raw = read_image(template_path, cv2.IMREAD_UNCHANGED)
        template, mask = self._split_template_and_mask(template_raw)
        haystack, offset = self._crop(screen, roi)

        th, tw = template.shape[:2]
        hh, hw = haystack.shape[:2]
        if th > hh or tw > hw:
            return None

        if mask is not None:
            result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED, mask=mask)
            result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        else:
            result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)

        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        confidence = float(max_val)
        min_score = self.threshold if threshold is None else threshold
        if confidence < min_score:
            return None

        x = int(max_loc[0] + offset[0])
        y = int(max_loc[1] + offset[1])
        return MatchResult(
            template_path=template_path,
            confidence=confidence,
            center=(x + tw // 2, y + th // 2),
            bbox=(x, y, tw, th),
        )

    def match_any(
        self,
        screen: np.ndarray,
        template_paths: Iterable[Path],
        threshold: Optional[float] = None,
        roi: Optional[Roi] = None,
    ) -> Optional[MatchResult]:
        best: Optional[MatchResult] = None
        for path in template_paths:
            result = self.match_template(screen, path, threshold=threshold, roi=roi)
            if result is None:
                continue
            if best is None or result.confidence > best.confidence:
                best = result
        return best

    def match_dir(
        self,
        screen: np.ndarray,
        template_dir: Path,
        pattern: str = "*.png",
        threshold: Optional[float] = None,
        roi: Optional[Roi] = None,
    ) -> Optional[MatchResult]:
        if not template_dir.exists():
            return None
        return self.match_any(
            screen,
            sorted(template_dir.glob(pattern)),
            threshold=threshold,
            roi=roi,
        )

    def save_debug(self, screen: np.ndarray, result: MatchResult, path: Path) -> Path:
        image = screen.copy()
        x, y, w, h = result.bbox
        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.circle(image, result.center, 4, (0, 255, 0), -1)
        label = f"{result.template_path.name} {result.confidence:.3f}"
        cv2.putText(
            image,
            label,
            (x, max(16, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
        return write_image(path, image)

    @staticmethod
    def _split_template_and_mask(template_raw: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        if template_raw.ndim == 3 and template_raw.shape[2] == 4:
            bgr = template_raw[:, :, :3]
            alpha = template_raw[:, :, 3]
            mask = cv2.threshold(alpha, 1, 255, cv2.THRESH_BINARY)[1]
            return bgr, mask
        if template_raw.ndim == 2:
            return cv2.cvtColor(template_raw, cv2.COLOR_GRAY2BGR), None
        return template_raw, None

    @staticmethod
    def _crop(screen: np.ndarray, roi: Optional[Roi]) -> Tuple[np.ndarray, Tuple[int, int]]:
        if roi is None:
            return screen, (0, 0)
        x, y, w, h = roi
        height, width = screen.shape[:2]
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(width, x1 + max(0, int(w)))
        y2 = min(height, y1 + max(0, int(h)))
        return screen[y1:y2, x1:x2], (x1, y1)
