from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image


DETECTOR_CLASS = "action_candidate"


def read_event(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_bbox(value: Any, width: int, height: int) -> tuple[float, float, float, float] | None:
    try:
        x, y, w, h = [float(v) for v in value]
    except Exception:
        return None
    if w <= 1 or h <= 1:
        return None
    x1 = max(0.0, min(float(width - 1), x))
    y1 = max(0.0, min(float(height - 1), y))
    x2 = max(x1 + 1.0, min(float(width), x + w))
    y2 = max(y1 + 1.0, min(float(height), y + h))
    return x1, y1, x2 - x1, y2 - y1


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def event_paths(collection_root: Path, date: str, max_events: int) -> list[Path]:
    pattern = f"click_success_{date}_*" if date else "click_success_*"
    paths = sorted(path / "event.json" for path in collection_root.glob(pattern) if (path / "event.json").exists())
    if max_events > 0:
        return paths[:max_events]
    return paths


def build(args: argparse.Namespace) -> None:
    output_dir: Path = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)

    screen_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    copied = 0
    ann_id = 0

    for event_json in event_paths(args.collection_root, args.date, args.max_events):
        event = read_event(event_json)
        if not event.get("verified_success"):
            skipped["not_verified_success"] += 1
            continue
        if float(event.get("screen_change_score") or 0.0) < args.min_screen_change:
            skipped["screen_change_below_threshold"] += 1
            continue
        parent = Path(event.get("pre_click_screenshot") or event.get("primary_review_image") or "")
        if not parent.exists():
            skipped["missing_parent_image"] += 1
            continue
        metadata = event.get("metadata") or {}
        detector_candidate = event.get("detector_training_candidate") or {}
        bbox_value = detector_candidate.get("bbox") or metadata.get("bbox")
        with Image.open(parent) as image:
            width, height = image.size
        bbox = normalize_bbox(bbox_value, width, height)
        if bbox is None:
            skipped["missing_or_invalid_bbox"] += 1
            continue

        copied += 1
        screen_id = f"click_det_{copied:06d}"
        image_name = f"{screen_id}.png"
        image_path = output_dir / "images" / image_name
        shutil.copy2(parent, image_path)
        source_session = event.get("source_session") or f"click_success:{event.get('event_id', copied)}"
        split_group = f"click_success:{source_session}"
        screen_rows.append(
            {
                "screen_id": screen_id,
                "image_path": str(image_path),
                "original_path": str(parent),
                "event_json": str(event_json),
                "event_id": event.get("event_id", ""),
                "source_session": source_session,
                "timestamp": event.get("timestamp", ""),
                "proposal_source": event.get("proposal_source", ""),
                "template_name": metadata.get("template_name", ""),
                "screen_change_score": event.get("screen_change_score", ""),
                "width": width,
                "height": height,
                "positive_bbox_count": 1,
                "dataset_role": "weak_positive",
                "split_group": split_group,
                "split": "",
            }
        )
        ann_id += 1
        x, y, w, h = bbox
        annotation_rows.append(
            {
                "annotation_id": f"click_ann_{ann_id:06d}",
                "screen_id": screen_id,
                "image_path": str(image_path),
                "event_id": event.get("event_id", ""),
                "source_session": source_session,
                "bbox_x": f"{x:.3f}",
                "bbox_y": f"{y:.3f}",
                "bbox_w": f"{w:.3f}",
                "bbox_h": f"{h:.3f}",
                "category": DETECTOR_CLASS,
                "label": "weak_positive",
                "proposal_source": event.get("proposal_source", ""),
                "template_name": metadata.get("template_name", ""),
                "screen_change_score": event.get("screen_change_score", ""),
                "split_group": split_group,
                "split": "",
            }
        )
        coco_images.append(
            {
                "id": copied,
                "file_name": f"images/{image_name}",
                "width": width,
                "height": height,
                "event_id": event.get("event_id", ""),
                "source_session": source_session,
            }
        )
        coco_annotations.append(
            {
                "id": ann_id,
                "image_id": copied,
                "category_id": 1,
                "bbox": [x, y, w, h],
                "area": w * h,
                "iscrowd": 0,
                "label_source": "click_success_weak_positive",
            }
        )

    screen_fields = [
        "screen_id",
        "image_path",
        "original_path",
        "event_json",
        "event_id",
        "source_session",
        "timestamp",
        "proposal_source",
        "template_name",
        "screen_change_score",
        "width",
        "height",
        "positive_bbox_count",
        "dataset_role",
        "split_group",
        "split",
    ]
    annotation_fields = [
        "annotation_id",
        "screen_id",
        "image_path",
        "event_id",
        "source_session",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "category",
        "label",
        "proposal_source",
        "template_name",
        "screen_change_score",
        "split_group",
        "split",
    ]
    write_csv(output_dir / "screens.csv", screen_rows, screen_fields)
    write_csv(output_dir / "annotations.csv", annotation_rows, annotation_fields)
    coco = {
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [{"id": 1, "name": DETECTOR_CLASS}],
    }
    (output_dir / "annotations_coco.json").write_text(json.dumps(coco, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "dataset_kind": "ads_detector_click_success_weak_positive",
        "collection_root": str(args.collection_root),
        "date": args.date,
        "min_screen_change": args.min_screen_change,
        "screens_exported": len(screen_rows),
        "annotations_exported": len(annotation_rows),
        "proposal_source_counts": dict(Counter(row["proposal_source"] for row in screen_rows)),
        "skipped": dict(skipped),
        "note": "Weak positives must be reviewed or isolated from final holdout before production training.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a weak detector dataset from click-success collection events.")
    parser.add_argument("--collection-root", type=Path, default=Path("vision_platform/ads/runtime_collection/click_success"))
    parser.add_argument("--date", default="")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-screen-change", type=float, default=2.0)
    parser.add_argument("--max-events", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    build(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
