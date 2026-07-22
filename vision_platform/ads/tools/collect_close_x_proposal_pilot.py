from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ads2.core.close_glyph import DEFAULT_CLOSE_GLYPHS, _match_one, _read_edge_template
from ads2.core.geometry_close import GeometryCloseSpec, match_geometry_close_rows
from src.vision_matcher import VisionMatcher, read_image, write_image


FAMILIES = ["x_mark", "play_triangle", "google_play", "next", "free", "got", "arrow"]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass
class Proposal:
    raw_proposal_id: str
    parent_screen_id: str
    parent_screen_path: Path
    bbox: tuple[int, int, int, int]
    proposal_source: str
    proposal_type: str
    proposal_score: float
    template_name: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return x + w / 2.0, y + h / 2.0


@dataclass
class Candidate:
    candidate_id: str
    parent_screen_id: str
    parent_screen_path: Path
    bbox: tuple[int, int, int, int]
    raw_proposals: list[Proposal]
    nms_group_id: str
    rank_score: float
    overflow: bool = False


def normalize_box(bbox: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = (int(v) for v in bbox)
    x1 = max(0, min(width - 1, x))
    y1 = max(0, min(height - 1, y))
    x2 = max(x1 + 1, min(width, x + max(1, w)))
    y2 = max(y1 + 1, min(height, y + max(1, h)))
    return x1, y1, x2 - x1, y2 - y1


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / max(union, 1)


def union_box(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    x1 = min(x for x, _y, _w, _h in boxes)
    y1 = min(y for _x, y, _w, _h in boxes)
    x2 = max(x + w for x, _y, w, _h in boxes)
    y2 = max(y + h for _x, y, _w, h in boxes)
    return x1, y1, x2 - x1, y2 - y1


def crop_bbox_np(image: np.ndarray, bbox: tuple[int, int, int, int], *, scale: float = 1.0) -> Image.Image:
    h, w = image.shape[:2]
    x, y, bw, bh = bbox
    cx = x + bw / 2.0
    cy = y + bh / 2.0
    side_w = max(1.0, bw * scale)
    side_h = max(1.0, bh * scale)
    left = int(math.floor(cx - side_w / 2.0))
    top = int(math.floor(cy - side_h / 2.0))
    right = int(math.ceil(cx + side_w / 2.0))
    bottom = int(math.ceil(cy + side_h / 2.0))
    left = max(0, left)
    top = max(0, top)
    right = min(w, max(left + 1, right))
    bottom = min(h, max(top + 1, bottom))
    crop = image[top:bottom, left:right]
    return Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))


def canonical_object(image: Image.Image, output_size: int = 96, object_ratio: float = 0.70) -> Image.Image:
    image = image.convert("RGB")
    target_max = max(1, round(output_size * object_ratio))
    scale = target_max / max(image.width, image.height, 1)
    new_w = max(1, round(image.width * scale))
    new_h = max(1, round(image.height * scale))
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (output_size, output_size), (0, 0, 0))
    canvas.paste(resized, ((output_size - new_w) // 2, (output_size - new_h) // 2))
    return canvas


def screen_paths(input_dir: Path, max_screens: int) -> list[Path]:
    paths = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    if max_screens > 0:
        return paths[:max_screens]
    return paths


def collect_template_proposals(
    screen: np.ndarray,
    screen_id: str,
    screen_path: Path,
    templates_dir: Path,
    *,
    threshold: float,
    roi: tuple[int, int, int, int],
    max_per_template: int,
) -> list[Proposal]:
    if not templates_dir.exists():
        return []
    matcher = VisionMatcher(threshold=threshold)
    proposals: list[Proposal] = []
    for template_path in sorted(templates_dir.rglob("*.png")):
        matches = matcher.match_template_all(
            screen,
            template_path,
            threshold=threshold,
            roi=roi,
            check_brightness=True,
            max_results=max_per_template,
            min_center_distance=18,
        )
        for match in matches:
            proposals.append(
                Proposal(
                    raw_proposal_id="",
                    parent_screen_id=screen_id,
                    parent_screen_path=screen_path,
                    bbox=tuple(int(v) for v in match.bbox),
                    proposal_source="close_template",
                    proposal_type="template_match",
                    proposal_score=float(match.confidence),
                    template_name=template_path.name,
                    raw_payload={"brightness_ratio": match.brightness_ratio},
                )
            )
    return proposals


def collect_glyph_proposals(
    screen: np.ndarray,
    screen_id: str,
    screen_path: Path,
    glyphs_dir: Path,
    *,
    roi: tuple[int, int, int, int],
) -> list[Proposal]:
    proposals: list[Proposal] = []
    for spec in DEFAULT_CLOSE_GLYPHS:
        template = _read_edge_template(glyphs_dir / spec.source_name)
        if template is None:
            continue
        result = _match_one(screen, template, spec, roi=roi)
        if result is None:
            continue
        proposals.append(
            Proposal(
                raw_proposal_id="",
                parent_screen_id=screen_id,
                parent_screen_path=screen_path,
                bbox=tuple(int(v) for v in result.bbox),
                proposal_source="close_glyph",
                proposal_type=spec.name,
                proposal_score=float(result.confidence),
                template_name=spec.source_name,
                raw_payload={
                    "threshold": spec.threshold,
                    "saturation_max": spec.saturation_max,
                    "value_min": spec.value_min,
                },
            )
        )
    return proposals


def collect_geometry_proposals(
    screen: np.ndarray,
    screen_id: str,
    screen_path: Path,
    *,
    threshold: float,
    roi_top_ratio: float,
    max_results: int,
) -> list[Proposal]:
    spec = GeometryCloseSpec(
        threshold=threshold,
        roi_top_ratio=roi_top_ratio,
        max_results=max_results,
        min_size=8,
        max_size=60,
        min_axis_union=0.55,
        min_axis_balance=0.20,
        min_length_ratio=0.70,
        max_center_offset=0.25,
    )
    rows = match_geometry_close_rows(screen, spec=spec)
    proposals = []
    for row in rows:
        payload = {key: value for key, value in row.items() if key not in {"bbox", "box", "center"}}
        proposals.append(
            Proposal(
                raw_proposal_id="",
                parent_screen_id=screen_id,
                parent_screen_path=screen_path,
                bbox=tuple(int(v) for v in row["bbox"]),
                proposal_source="geometry_x",
                proposal_type="x_geometry",
                proposal_score=float(row.get("score", 0.0)),
                template_name="__geometry_close.png",
                raw_payload=payload,
            )
        )
    return proposals


def assign_raw_ids(proposals: list[Proposal], screen_index: int) -> None:
    for index, proposal in enumerate(proposals, start=1):
        proposal.raw_proposal_id = f"raw_s{screen_index:04d}_{index:04d}"


def merge_proposals(
    proposals: list[Proposal],
    *,
    iou_threshold: float,
    max_candidates: int,
    screen_index: int,
) -> tuple[list[Candidate], list[Candidate]]:
    sorted_props = sorted(proposals, key=lambda item: item.proposal_score, reverse=True)
    groups: list[list[Proposal]] = []
    for proposal in sorted_props:
        best_group = None
        best_iou = 0.0
        for group in groups:
            group_box = union_box([item.bbox for item in group])
            overlap = iou(proposal.bbox, group_box)
            if overlap > best_iou:
                best_iou = overlap
                best_group = group
        if best_group is not None and best_iou >= iou_threshold:
            best_group.append(proposal)
        else:
            groups.append([proposal])

    candidates: list[Candidate] = []
    for group_index, group in enumerate(groups, start=1):
        bbox = union_box([item.bbox for item in group])
        score = max(item.proposal_score for item in group)
        candidate_id = f"cxp_s{screen_index:04d}_{group_index:03d}"
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                parent_screen_id=group[0].parent_screen_id,
                parent_screen_path=group[0].parent_screen_path,
                bbox=bbox,
                raw_proposals=group,
                nms_group_id=f"nms_s{screen_index:04d}_{group_index:03d}",
                rank_score=score,
            )
        )
    candidates.sort(key=lambda item: item.rank_score, reverse=True)
    kept = candidates[:max_candidates]
    overflow = candidates[max_candidates:]
    for item in overflow:
        item.overflow = True
    return kept, overflow


class VisualFamilyScorer:
    def __init__(self, checkpoint_path: Path, *, device: str = "cpu", output_size: int = 96):
        self.checkpoint_path = checkpoint_path
        self.device_name = device
        self.output_size = output_size
        self.ready = checkpoint_path.exists()
        self._model = None
        self._transform = None
        self._device = None
        self.families = FAMILIES

    def score(self, image: Image.Image) -> dict[str, float]:
        if not self.ready:
            return {f"p_{family}": "" for family in self.families}
        self._load()
        import torch

        with torch.no_grad():
            tensor = self._transform(image.convert("RGB")).unsqueeze(0).to(self._device)
            probs = torch.sigmoid(self._model(tensor))[0].cpu().numpy()
        return {f"p_{family}": round(float(probs[index]), 5) for index, family in enumerate(self.families)}

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from torchvision import models, transforms
        from torchvision.models import MobileNet_V3_Small_Weights

        weights = MobileNet_V3_Small_Weights.DEFAULT
        device = torch.device(self.device_name)
        model = models.mobilenet_v3_small(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, len(self.families))
        checkpoint = torch.load(self.checkpoint_path, map_location=device, weights_only=False)
        model.load_state_dict(checkpoint["model"])
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


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def draw_overlay(screen: np.ndarray, candidates: list[Candidate], output_path: Path) -> None:
    rgb = cv2.cvtColor(screen, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for index, candidate in enumerate(candidates, start=1):
        x, y, w, h = candidate.bbox
        color = (255, 48, 48)
        draw.rectangle((x, y, x + w, y + h), outline=color, width=2)
        draw.text((x, max(0, y - 12)), f"{index}:{candidate.rank_score:.2f}", fill=color, font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def save_candidate_images(screen: np.ndarray, candidate: Candidate, output_dir: Path, scorer: VisualFamilyScorer) -> dict[str, Any]:
    root_name = "overflow_crops" if candidate.overflow else "crops"
    raw_dir = output_dir / root_name / "raw_bbox"
    context_dir = output_dir / root_name / "context_1_5x"
    canonical_dir = output_dir / root_name / "canonical_96"
    raw_crop_path = raw_dir / f"{candidate.candidate_id}_bbox.png"
    context_crop_path = context_dir / f"{candidate.candidate_id}_context.png"
    canonical_path = canonical_dir / f"{candidate.candidate_id}_canonical.png"
    raw = crop_bbox_np(screen, candidate.bbox, scale=1.0)
    context = crop_bbox_np(screen, candidate.bbox, scale=1.5)
    canonical = canonical_object(raw)
    raw_crop_path.parent.mkdir(parents=True, exist_ok=True)
    context_crop_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    raw.save(raw_crop_path)
    context.save(context_crop_path)
    canonical.save(canonical_path)
    scores = scorer.score(canonical)
    return {
        "raw_bbox_crop_path": str(raw_crop_path),
        "context_crop_path": str(context_crop_path),
        "canonical_crop_path": str(canonical_path),
        **scores,
    }


def save_raw_proposal_crop(screen: np.ndarray, proposal: Proposal, output_dir: Path) -> str:
    path = output_dir / "raw_proposal_crops" / f"{proposal.raw_proposal_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    crop_bbox_np(screen, proposal.bbox, scale=1.0).save(path)
    return str(path)


def source_session_for(path: Path) -> str:
    return path.parent.name or "unknown_session"


def collect(args: argparse.Namespace) -> None:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or Path("vision_platform/ads/collections") / f"close_x_proposal_collection_pilot_{timestamp}"
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    assets_dir = Path("ads2/assets/1_templates")
    close_icons_dir = args.close_icons_dir or assets_dir / "close_icons"
    close_glyphs_dir = args.close_glyphs_dir or assets_dir / "close_glyphs"
    scorer = VisualFamilyScorer(args.classifier_checkpoint, device=args.classifier_device)

    screens = screen_paths(args.input_dir, args.max_screens)
    raw_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    overflow_rows: list[dict[str, Any]] = []
    screen_rows: list[dict[str, Any]] = []
    proposal_source_counts: dict[str, int] = {}
    expected_family_by_source = {
        "close_template": ["x_mark", "google_play", "next", "arrow"],
        "close_glyph": ["google_play", "next"],
        "geometry_x": ["x_mark"],
    }

    for screen_index, source_path in enumerate(screens, start=1):
        screen = read_image(source_path, cv2.IMREAD_COLOR)
        if screen is None or screen.size == 0:
            continue
        height, width = screen.shape[:2]
        screen_id = f"screen_{screen_index:04d}"
        copied_screen = output_dir / "screens" / f"{screen_id}{source_path.suffix.lower() or '.png'}"
        copied_screen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, copied_screen)
        roi = (0, 0, width, int(height * args.close_roi_top_ratio))

        proposals: list[Proposal] = []
        proposals.extend(
            collect_template_proposals(
                screen,
                screen_id,
                copied_screen,
                close_icons_dir,
                threshold=args.close_template_threshold,
                roi=roi,
                max_per_template=args.max_template_matches_per_template,
            )
        )
        proposals.extend(collect_glyph_proposals(screen, screen_id, copied_screen, close_glyphs_dir, roi=roi))
        proposals.extend(
            collect_geometry_proposals(
                screen,
                screen_id,
                copied_screen,
                threshold=args.geometry_threshold,
                roi_top_ratio=args.close_roi_top_ratio,
                max_results=args.max_geometry_candidates,
            )
        )
        proposals = [
            Proposal(
                **{
                    **proposal.__dict__,
                    "bbox": normalize_box(proposal.bbox, width, height),
                }
            )
            for proposal in proposals
        ]
        assign_raw_ids(proposals, screen_index)
        for proposal in proposals:
            proposal_source_counts[proposal.proposal_source] = proposal_source_counts.get(proposal.proposal_source, 0) + 1
            raw_crop = save_raw_proposal_crop(screen, proposal, output_dir)
            x, y, w, h = proposal.bbox
            raw_rows.append(
                {
                    "raw_proposal_id": proposal.raw_proposal_id,
                    "parent_screen_id": screen_id,
                    "parent_screen_path": str(copied_screen),
                    "source_screen_path": str(source_path),
                    "bbox": json_text(list(proposal.bbox)),
                    "bbox_x": x,
                    "bbox_y": y,
                    "bbox_w": w,
                    "bbox_h": h,
                    "proposal_source": proposal.proposal_source,
                    "proposal_type": proposal.proposal_type,
                    "proposal_score": round(proposal.proposal_score, 6),
                    "template_name": proposal.template_name,
                    "raw_proposal_crop_path": raw_crop,
                    "raw_payload": json_text(proposal.raw_payload),
                }
            )

        kept, overflow = merge_proposals(
            proposals,
            iou_threshold=args.nms_iou_threshold,
            max_candidates=args.max_candidates_per_screen,
            screen_index=screen_index,
        )
        overlay_path = output_dir / "overlays" / f"{screen_id}_overlay.png"
        draw_overlay(screen, kept, overlay_path)
        split_group = f"{source_session_for(source_path)}:{screen_id}"
        for candidate in kept + overflow:
            image_paths = save_candidate_images(screen, candidate, output_dir, scorer)
            x, y, w, h = candidate.bbox
            sources = sorted({proposal.proposal_source for proposal in candidate.raw_proposals})
            types = sorted({proposal.proposal_type for proposal in candidate.raw_proposals})
            scores = [proposal.proposal_score for proposal in candidate.raw_proposals]
            row = {
                "candidate_id": candidate.candidate_id,
                "parent_screen_id": screen_id,
                "parent_screen_path": str(copied_screen),
                "source_screen_path": str(source_path),
                "source_session": source_session_for(source_path),
                "timestamp": timestamp,
                "creative_id_or_group": source_session_for(source_path),
                "bbox": json_text(list(candidate.bbox)),
                "bbox_x": x,
                "bbox_y": y,
                "bbox_w": w,
                "bbox_h": h,
                "raw_bbox_crop_path": image_paths["raw_bbox_crop_path"],
                "context_crop_path": image_paths["context_crop_path"],
                "canonical_crop_path": image_paths["canonical_crop_path"],
                "overlay_path": str(overlay_path),
                "proposal_sources": "|".join(sources),
                "proposal_types": "|".join(types),
                "proposal_scores": "|".join(f"{score:.6f}" for score in scores),
                "proposal_score_max": round(max(scores), 6) if scores else 0.0,
                "raw_proposal_ids": "|".join(proposal.raw_proposal_id for proposal in candidate.raw_proposals),
                "nms_group_id": candidate.nms_group_id,
                "raw_proposal_count": len(candidate.raw_proposals),
                "overflow": int(candidate.overflow),
                "review_status": "pending",
                "visual_families": "",
                "is_holdout": int(args.holdout),
                "split_group": split_group,
                **{f"classifier_{family}": image_paths.get(f"p_{family}", "") for family in FAMILIES},
            }
            if candidate.overflow:
                overflow_rows.append(row)
            else:
                manifest_rows.append(row)
        screen_rows.append(
            {
                "parent_screen_id": screen_id,
                "source_screen_path": str(source_path),
                "copied_screen_path": str(copied_screen),
                "source_session": source_session_for(source_path),
                "width": width,
                "height": height,
                "raw_proposals": len(proposals),
                "candidates_kept": len(kept),
                "candidates_overflow": len(overflow),
                "overlay_path": str(overlay_path),
                "split_group": split_group,
            }
        )

    raw_fields = [
        "raw_proposal_id",
        "parent_screen_id",
        "parent_screen_path",
        "source_screen_path",
        "bbox",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "proposal_source",
        "proposal_type",
        "proposal_score",
        "template_name",
        "raw_proposal_crop_path",
        "raw_payload",
    ]
    manifest_fields = [
        "candidate_id",
        "parent_screen_id",
        "parent_screen_path",
        "source_screen_path",
        "source_session",
        "timestamp",
        "creative_id_or_group",
        "bbox",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "raw_bbox_crop_path",
        "context_crop_path",
        "canonical_crop_path",
        "overlay_path",
        "proposal_sources",
        "proposal_types",
        "proposal_scores",
        "proposal_score_max",
        "raw_proposal_ids",
        "nms_group_id",
        "raw_proposal_count",
        "overflow",
        "review_status",
        "visual_families",
        "is_holdout",
        "split_group",
        *[f"classifier_{family}" for family in FAMILIES],
    ]
    write_csv(output_dir / "raw_proposals.csv", raw_rows, raw_fields)
    write_csv(output_dir / "manifest.csv", manifest_rows, manifest_fields)
    write_csv(output_dir / "overflow.csv", overflow_rows, manifest_fields)
    write_csv(
        output_dir / "screens.csv",
        screen_rows,
        [
            "parent_screen_id",
            "source_screen_path",
            "copied_screen_path",
            "source_session",
            "width",
            "height",
            "raw_proposals",
            "candidates_kept",
            "candidates_overflow",
            "overlay_path",
            "split_group",
        ],
    )
    config = {
        "collection_name": "close_x_proposal_collection_pilot",
        "input_dir": str(args.input_dir),
        "output_dir": str(output_dir),
        "max_screens": args.max_screens,
        "proposal_sources": {
            "close_template": {
                "enabled": True,
                "threshold": args.close_template_threshold,
                "expected_visual_families": expected_family_by_source["close_template"],
            },
            "close_glyph": {
                "enabled": True,
                "expected_visual_families": expected_family_by_source["close_glyph"],
            },
            "geometry_x": {
                "enabled": True,
                "threshold": args.geometry_threshold,
                "expected_visual_families": expected_family_by_source["geometry_x"],
            },
        },
        "nms_iou_threshold": args.nms_iou_threshold,
        "max_candidates_per_screen": args.max_candidates_per_screen,
        "classifier_checkpoint": str(args.classifier_checkpoint),
        "classifier_probabilities_in_manifest_only": True,
    }
    (output_dir / "collection_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "collection_name": "close_x_proposal_collection_pilot",
        "scope_warning": "This first pilot primarily uses close template/glyph/geometry-X proposal sources; it is not a complete seven-family detector evaluation.",
        "screens_scanned": len(screen_rows),
        "raw_proposals": len(raw_rows),
        "candidates_kept": len(manifest_rows),
        "candidates_overflow": len(overflow_rows),
        "proposal_source_counts": proposal_source_counts,
        "expected_family_by_source": expected_family_by_source,
        "output_dir": str(output_dir),
        "raw_proposals_csv": str(output_dir / "raw_proposals.csv"),
        "manifest_csv": str(output_dir / "manifest.csv"),
        "overflow_csv": str(output_dir / "overflow.csv"),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Close-X Proposal Collection Pilot",
        "",
        "This is a close_x proposal collection pilot. It primarily uses close template, close glyph, and geometry-X proposal sources.",
        "It is not a complete detector evaluation for all seven visual families.",
        "",
        f"- Screens scanned: {len(screen_rows)}",
        f"- Raw proposals: {len(raw_rows)}",
        f"- NMS candidates kept for GUI: {len(manifest_rows)}",
        f"- Overflow candidates: {len(overflow_rows)}",
        "",
        "## Proposal Sources",
    ]
    for source, families in expected_family_by_source.items():
        lines.append(f"- `{source}`: expected coverage {', '.join(families)}; count={proposal_source_counts.get(source, 0)}")
    lines += [
        "",
        "## Files",
        "",
        f"- Raw proposals: `{output_dir / 'raw_proposals.csv'}`",
        f"- GUI manifest: `{output_dir / 'manifest.csv'}`",
        f"- Overflow: `{output_dir / 'overflow.csv'}`",
        f"- Config: `{output_dir / 'collection_config.json'}`",
    ]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    gui_config = {
        "default_filter": {
            "domain": "ads_shared",
            "role": "candidate_crop",
            "scope": "crop",
            "source": "vision_platform\\ads\\collections",
            "status": "all",
            "visual_status": "unreviewed",
            "search": output_dir.name,
            "sort": "image_signature",
            "include_path_any": [f"{output_dir.name}\\crops\\raw_bbox"],
        },
        "sort_mode": "image_signature",
    }
    gui_config_path = output_dir / "review_gui_config.json"
    gui_config_path.write_text(json.dumps(gui_config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"GUI config: {gui_config_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect close-X proposal candidates from offline full-screen ad screenshots.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory containing new full-screen screenshots.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-screens", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--close-icons-dir", type=Path, default=None)
    parser.add_argument("--close-glyphs-dir", type=Path, default=None)
    parser.add_argument("--close-template-threshold", type=float, default=0.72)
    parser.add_argument("--geometry-threshold", type=float, default=0.45)
    parser.add_argument("--close-roi-top-ratio", type=float, default=0.45)
    parser.add_argument("--max-template-matches-per-template", type=int, default=3)
    parser.add_argument("--max-geometry-candidates", type=int, default=40)
    parser.add_argument("--nms-iou-threshold", type=float, default=0.45)
    parser.add_argument("--max-candidates-per-screen", type=int, default=20)
    parser.add_argument("--holdout", action="store_true", help="Mark manifest rows as holdout candidates.")
    parser.add_argument(
        "--classifier-checkpoint",
        type=Path,
        default=Path("vision_platform/ads/pilot/visual_family_smoke/run_seed42/best.pt"),
    )
    parser.add_argument("--classifier-device", default="cpu")
    args = parser.parse_args()
    collect(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
