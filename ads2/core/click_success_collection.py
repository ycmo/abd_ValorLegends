from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class ClickSuccessRecord:
    event_dir: Path
    event_json: Path


class ClickSuccessCollector:
    """Collect weak positive click evidence for later human review.

    A saved event means "a runtime click caused a meaningful screen change",
    not "this is already a trusted training label".
    """

    def __init__(
        self,
        *,
        collection_dir: Path,
        change_threshold: float = 2.0,
        click_crop_sizes: tuple[int, ...] = (64, 96, 160),
    ):
        self.collection_dir = collection_dir
        self.change_threshold = float(change_threshold)
        self.click_crop_sizes = click_crop_sizes

    def screen_change_score(self, before: np.ndarray | None, after: np.ndarray | None) -> float:
        if before is None or after is None:
            return 0.0
        try:
            before_small = cv2.resize(before, (160, 90), interpolation=cv2.INTER_AREA)
            after_small = cv2.resize(after, (160, 90), interpolation=cv2.INTER_AREA)
            before_gray = cv2.cvtColor(before_small, cv2.COLOR_BGR2GRAY)
            after_gray = cv2.cvtColor(after_small, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(before_gray, after_gray)
            return float(diff.mean())
        except Exception:
            return 0.0

    def maybe_record(
        self,
        *,
        before_screen: np.ndarray | None,
        after_screen: np.ndarray | None,
        click_xy: tuple[int, int],
        proposal_source: str,
        verified_success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> ClickSuccessRecord | None:
        score = self.screen_change_score(before_screen, after_screen)
        if not verified_success or score < self.change_threshold:
            return None
        return self.record(
            before_screen=before_screen,
            after_screen=after_screen,
            click_xy=click_xy,
            proposal_source=proposal_source,
            verified_success=verified_success,
            screen_change_score=score,
            metadata=metadata or {},
        )

    def record(
        self,
        *,
        before_screen: np.ndarray | None,
        after_screen: np.ndarray | None,
        click_xy: tuple[int, int],
        proposal_source: str,
        verified_success: bool,
        screen_change_score: float,
        metadata: dict[str, Any],
    ) -> ClickSuccessRecord:
        event_id = time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"
        event_dir = self.collection_dir / f"click_success_{event_id}"
        crops_dir = event_dir / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        before_path = event_dir / "pre_click.png"
        after_path = event_dir / "post_click.png"
        if before_screen is not None:
            _write_bgr(before_path, before_screen)
        if after_screen is not None:
            _write_bgr(after_path, after_screen)

        click_crops = []
        if before_screen is not None:
            for size in self.click_crop_sizes:
                crop_path = crops_dir / f"click_{size}px.png"
                _write_bgr(crop_path, _crop_square_center(before_screen, click_xy, size))
                click_crops.append({"size": size, "path": str(crop_path.resolve())})

        bbox = _normalize_bbox(metadata.get("bbox"))
        bbox_crop_path = ""
        bbox_context_path = ""
        if before_screen is not None and bbox is not None:
            bbox_crop_path = str((crops_dir / "bbox.png").resolve())
            _write_bgr(Path(bbox_crop_path), _crop_bbox(before_screen, bbox, scale=1.0))
            bbox_context_path = str((crops_dir / "bbox_context_1_5x.png").resolve())
            _write_bgr(Path(bbox_context_path), _crop_bbox(before_screen, bbox, scale=1.5))

        payload = {
            "event_id": event_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": "ads2",
            "source_session": f"ads2_click_success_{event_id}",
            "weak_label": "weak_action_target",
            "review_status": "pending",
            "verified_success": bool(verified_success),
            "screen_change_score": screen_change_score,
            "screen_change_threshold": self.change_threshold,
            "proposal_source": proposal_source,
            "click_xy": [int(click_xy[0]), int(click_xy[1])],
            "pre_click_screenshot": str(before_path.resolve()) if before_screen is not None else "",
            "post_click_screenshot": str(after_path.resolve()) if after_screen is not None else "",
            "click_crops": click_crops,
            "bbox_crop": bbox_crop_path,
            "bbox_context_crop": bbox_context_path,
            "metadata": _json_safe(metadata),
        }
        event_json = event_dir / "event.json"
        event_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ClickSuccessRecord(event_dir=event_dir, event_json=event_json)


def _normalize_bbox(value: Any) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    try:
        x, y, w, h = value
        return int(x), int(y), int(w), int(h)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def _crop_square_center(screen: np.ndarray, center: tuple[int, int], size: int) -> np.ndarray:
    cx, cy = center
    half = max(1, size // 2)
    return _crop_with_padding(screen, cx - half, cy - half, size, size)


def _crop_bbox(screen: np.ndarray, bbox: tuple[int, int, int, int], *, scale: float) -> np.ndarray:
    x, y, w, h = bbox
    side = max(1, int(round(max(w, h) * scale)))
    cx = x + w / 2
    cy = y + h / 2
    return _crop_with_padding(screen, int(round(cx - side / 2)), int(round(cy - side / 2)), side, side)


def _crop_with_padding(screen: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    height, width = screen.shape[:2]
    channels = 1 if screen.ndim == 2 else screen.shape[2]
    if channels == 1:
        canvas = np.zeros((h, w), dtype=screen.dtype)
    else:
        canvas = np.zeros((h, w, channels), dtype=screen.dtype)

    src_x1 = max(0, x)
    src_y1 = max(0, y)
    src_x2 = min(width, x + w)
    src_y2 = min(height, y + h)
    if src_x2 <= src_x1 or src_y2 <= src_y1:
        return canvas

    dst_x1 = src_x1 - x
    dst_y1 = src_y1 - y
    canvas[dst_y1 : dst_y1 + (src_y2 - src_y1), dst_x1 : dst_x1 + (src_x2 - src_x1)] = screen[src_y1:src_y2, src_x1:src_x2]
    return canvas


def _write_bgr(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    path.write_bytes(buf.tobytes())
