from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image


@dataclass
class CloseXClassifierCandidate:
    candidate_id: str
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    geometry_score: float
    p_close: float
    rank: int
    crop_path: Path
    clicked: bool = False
    screen_changed: bool | None = None
    after_screenshot_path: Path | None = None


@dataclass
class CloseXClassifierEvent:
    event_id: str
    event_dir: Path
    manifest_path: Path
    screenshot_path: Path
    source_session: str
    candidates: list[CloseXClassifierCandidate]


class CloseXClassifierRuntime:
    def __init__(
        self,
        *,
        checkpoint_path: Path,
        collection_dir: Path,
        threshold: float = 0.5,
        device: str = "cpu",
        output_size: int = 96,
        object_ratio: float = 0.70,
    ):
        self.checkpoint_path = checkpoint_path
        self.collection_dir = collection_dir
        self.threshold = threshold
        self.device_name = device
        self.output_size = output_size
        self.object_ratio = object_ratio
        self._model = None
        self._transform = None
        self._device = None

    @property
    def ready(self) -> bool:
        return self.checkpoint_path.exists()

    def score_event(self, screen: np.ndarray, geometry_rows: Iterable[dict]) -> CloseXClassifierEvent:
        if not self.ready:
            raise FileNotFoundError(self.checkpoint_path)
        self._load_model()

        event_id = time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"
        source_session = f"runtime_{event_id}"
        event_dir = self.collection_dir / source_session
        crop_dir = event_dir / "candidates"
        crop_dir.mkdir(parents=True, exist_ok=True)

        screenshot_path = event_dir / "screen.png"
        _write_bgr(screenshot_path, screen)

        candidates = []
        for index, row in enumerate(geometry_rows, start=1):
            bbox = tuple(int(v) for v in row["bbox"])
            crop = _canonical_object(_crop_bbox(screen, bbox), self.output_size, self.object_ratio)
            crop_path = crop_dir / f"cand_{index:03d}.png"
            crop.save(crop_path)
            p_close = self._score(crop)
            x, y, w, h = bbox
            candidates.append(
                CloseXClassifierCandidate(
                    candidate_id=f"cand_{index:03d}",
                    bbox=bbox,
                    center=(x + w // 2, y + h // 2),
                    geometry_score=float(row.get("score", 0.0)),
                    p_close=p_close,
                    rank=0,
                    crop_path=crop_path,
                )
            )

        candidates.sort(key=lambda item: item.p_close, reverse=True)
        for rank, candidate in enumerate(candidates, start=1):
            candidate.rank = rank

        event = CloseXClassifierEvent(
            event_id=event_id,
            event_dir=event_dir,
            manifest_path=event_dir / "event.json",
            screenshot_path=screenshot_path,
            source_session=source_session,
            candidates=candidates,
        )
        self.write_event(event)
        return event

    def mark_attempt(
        self,
        event: CloseXClassifierEvent,
        candidate: CloseXClassifierCandidate,
        *,
        after_screen: np.ndarray | None,
        screen_changed: bool,
    ) -> None:
        candidate.clicked = True
        candidate.screen_changed = screen_changed
        if after_screen is not None:
            after_path = event.event_dir / f"after_{candidate.candidate_id}.png"
            _write_bgr(after_path, after_screen)
            candidate.after_screenshot_path = after_path
        self.write_event(event)

    def write_event(self, event: CloseXClassifierEvent) -> None:
        payload = {
            "event_id": event.event_id,
            "source_session": event.source_session,
            "timestamp": event.event_id,
            "full_screenshot": str(event.screenshot_path.resolve()),
            "threshold": self.threshold,
            "selected_candidate": _selected_candidate_id(event.candidates),
            "whether_clicked": any(candidate.clicked for candidate in event.candidates),
            "candidates": [_candidate_payload(candidate) for candidate in event.candidates],
        }
        event.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_model(self) -> None:
        if self._model is not None:
            return
        import torch
        from torchvision import models, transforms
        from torchvision.models import MobileNet_V3_Small_Weights

        weights = MobileNet_V3_Small_Weights.DEFAULT
        device = torch.device(self.device_name)
        model = models.mobilenet_v3_small(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, 2)
        checkpoint_data = torch.load(self.checkpoint_path, map_location=device, weights_only=False)
        model.load_state_dict(checkpoint_data["model"])
        model.to(device)
        model.eval()
        self._model = model
        self._device = device
        self._transform = transforms.Compose(
            [
                transforms.Resize((self.output_size, self.output_size), interpolation=transforms.InterpolationMode.BILINEAR),
                transforms.ToTensor(),
                transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std),
            ]
        )

    def _score(self, image: Image.Image) -> float:
        import torch

        assert self._model is not None
        assert self._transform is not None
        assert self._device is not None
        with torch.no_grad():
            tensor = self._transform(image).unsqueeze(0).to(self._device)
            logits = self._model(tensor)
            return float(torch.softmax(logits, dim=1)[0, 1].cpu())


def _selected_candidate_id(candidates: list[CloseXClassifierCandidate]) -> str:
    clicked = [candidate for candidate in candidates if candidate.clicked]
    if not clicked:
        return ""
    clicked.sort(key=lambda candidate: candidate.rank)
    return clicked[0].candidate_id


def _candidate_payload(candidate: CloseXClassifierCandidate) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "bbox": list(candidate.bbox),
        "center": list(candidate.center),
        "geometry_score": candidate.geometry_score,
        "p_close": candidate.p_close,
        "rank": candidate.rank,
        "crop_path": str(candidate.crop_path.resolve()),
        "clicked": candidate.clicked,
        "screen_changed": candidate.screen_changed,
        "after_screenshot_path": "" if candidate.after_screenshot_path is None else str(candidate.after_screenshot_path.resolve()),
    }


def _crop_bbox(screen: np.ndarray, bbox: tuple[int, int, int, int]) -> Image.Image:
    x, y, w, h = bbox
    height, width = screen.shape[:2]
    left = max(0, x)
    top = max(0, y)
    right = min(width, x + w)
    bottom = min(height, y + h)
    if right <= left or bottom <= top:
        return Image.new("RGB", (1, 1), (0, 0, 0))
    crop = screen[top:bottom, left:right]
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _canonical_object(image: Image.Image, output_size: int, object_ratio: float) -> Image.Image:
    image = image.convert("RGB")
    target_max = max(1, round(output_size * object_ratio))
    scale = target_max / max(image.width, image.height)
    new_w = max(1, round(image.width * scale))
    new_h = max(1, round(image.height * scale))
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (output_size, output_size), (0, 0, 0))
    canvas.paste(resized, ((output_size - new_w) // 2, (output_size - new_h) // 2))
    return canvas


def _write_bgr(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    path.write_bytes(buf.tobytes())
