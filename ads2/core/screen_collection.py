from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class ScreenCollectionRecord:
    event_dir: Path
    event_json: Path


class AdsScreenCollector:
    """Collect raw Ads runtime screenshots for later detector review.

    These records are intentionally unlabeled. They capture what the Ads runtime
    saw, not whether a click should happen.
    """

    def __init__(
        self,
        *,
        collection_dir: Path,
        source_session: str | None = None,
        min_interval_seconds: float = 0.0,
    ):
        self.collection_dir = collection_dir
        self.source_session = source_session or _make_session_id()
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.sequence = 0
        self._last_record_time = 0.0

    def maybe_record(
        self,
        screen: np.ndarray | None,
        *,
        capture_reason: str = "runtime_screenshot",
        metadata: dict[str, Any] | None = None,
    ) -> ScreenCollectionRecord | None:
        if screen is None:
            return None
        now = time.time()
        if self.min_interval_seconds > 0 and now - self._last_record_time < self.min_interval_seconds:
            return None
        self._last_record_time = now
        return self.record(screen, capture_reason=capture_reason, metadata=metadata or {})

    def record(
        self,
        screen: np.ndarray,
        *,
        capture_reason: str,
        metadata: dict[str, Any],
    ) -> ScreenCollectionRecord:
        self.sequence += 1
        event_id = time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}_{self.sequence:06d}"
        event_dir = self.collection_dir / self.source_session / f"screen_{event_id}"
        event_dir.mkdir(parents=True, exist_ok=True)

        screen_path = event_dir / "screen.png"
        encoded = _encode_png(screen)
        screen_path.write_bytes(encoded)
        content_sha256 = hashlib.sha256(encoded).hexdigest()

        height, width = screen.shape[:2]
        payload = {
            "event_id": event_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": "ads2",
            "source_session": self.source_session,
            "collection_kind": "ads_raw_screen",
            "review_status": "pending",
            "primary_review_image": str(screen_path.resolve()),
            "primary_review_scope": "fullscreen",
            "screen_path": str(screen_path.resolve()),
            "width": int(width),
            "height": int(height),
            "sequence": int(self.sequence),
            "capture_reason": capture_reason,
            "content_sha256": content_sha256,
            "metadata": _json_safe(metadata),
        }
        event_json = event_dir / "event.json"
        event_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ScreenCollectionRecord(event_dir=event_dir, event_json=event_json)


def _make_session_id() -> str:
    return "ads2_screen_" + time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"


def _encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Cannot encode runtime screenshot")
    return buf.tobytes()


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
