from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DETECTOR_CLASS = "action_candidate"
DEFAULT_DOMAINS = ("ads", "shared")
EXCLUDED_REPRESENTATIONS = {"annotated", "debug_overlay", "edge_glyph", "binary_mask"}


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def reviewed_screens(con: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    domains = tuple(args.domains)
    placeholders = ",".join("?" for _ in domains)
    clauses = [
        "r.review_status = 'reviewed'",
        f"r.vision_domain IN ({placeholders})",
        "a.image_scope = 'fullscreen'",
        "r.screen_state IN ('actionable', 'waiting', 'returned_to_game')",
    ]
    params: list[Any] = list(domains)
    if not args.include_annotated:
        placeholders_repr = ",".join("?" for _ in EXCLUDED_REPRESENTATIONS)
        clauses.append(f"COALESCE(r.representation, 'unknown') NOT IN ({placeholders_repr})")
        params.extend(sorted(EXCLUDED_REPRESENTATIONS))
    if args.path_contains:
        clauses.append("a.relative_path LIKE ?")
        params.append(f"%{args.path_contains}%")
    where = " AND ".join(clauses)
    return con.execute(
        f"""
        SELECT
            a.instance_id,
            a.content_id,
            a.original_path,
            a.relative_path,
            a.filename,
            a.width,
            a.height,
            COALESCE(a.source_root, '') AS source_root,
            r.vision_domain,
            r.asset_type,
            r.representation,
            r.screen_state
        FROM assets a
        JOIN image_reviews r ON r.instance_id = a.instance_id
        WHERE {where}
        ORDER BY a.relative_path COLLATE NOCASE
        """,
        params,
    ).fetchall()


def bboxes_for(con: sqlite3.Connection, instance_ids: list[str]) -> dict[str, list[sqlite3.Row]]:
    if not instance_ids:
        return {}
    result: dict[str, list[sqlite3.Row]] = defaultdict(list)
    batch_size = 500
    for start in range(0, len(instance_ids), batch_size):
        batch = instance_ids[start : start + batch_size]
        placeholders = ",".join("?" for _ in batch)
        rows = con.execute(
            f"""
            SELECT
                b.id AS bbox_id,
                b.instance_id,
                b.x,
                b.y,
                b.w,
                b.h,
                b.label,
                COALESCE(c.name, '') AS class_name,
                b.note
            FROM bboxes b
            LEFT JOIN classes c ON c.id = b.class_id
            WHERE b.instance_id IN ({placeholders})
            ORDER BY b.instance_id, b.id
            """,
            batch,
        ).fetchall()
        for row in rows:
            result[row["instance_id"]].append(row)
    return result


def valid_positive_bbox(box: sqlite3.Row, width: int, height: int) -> bool:
    if box["label"] != "positive":
        return False
    class_name = str(box["class_name"] or "")
    if class_name and class_name != "action_target":
        return False
    x, y, w, h = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
    if w <= 1 or h <= 1:
        return False
    if x >= width or y >= height or x + w <= 0 or y + h <= 0:
        return False
    return True


def clamp_bbox(box: sqlite3.Row, width: int, height: int) -> tuple[float, float, float, float]:
    x = max(0.0, min(float(width - 1), float(box["x"])))
    y = max(0.0, min(float(height - 1), float(box["y"])))
    x2 = max(x + 1.0, min(float(width), float(box["x"]) + float(box["w"])))
    y2 = max(y + 1.0, min(float(height), float(box["y"]) + float(box["h"])))
    return x, y, x2 - x, y2 - y


def build(args: argparse.Namespace) -> None:
    output_dir: Path = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)

    con = open_db(args.db)
    screens = reviewed_screens(con, args)
    boxes_by_instance = bboxes_for(con, [row["instance_id"] for row in screens])

    screen_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    copied = 0
    ann_id = 0

    for screen_index, screen in enumerate(screens, start=1):
        width = int(screen["width"] or 0)
        height = int(screen["height"] or 0)
        if width <= 0 or height <= 0:
            skipped["invalid_dimensions"] += 1
            continue
        source = Path(screen["original_path"])
        if not source.exists():
            skipped["missing_file"] += 1
            continue
        raw_boxes = boxes_by_instance.get(screen["instance_id"], [])
        positives = [box for box in raw_boxes if valid_positive_bbox(box, width, height)]
        if screen["screen_state"] == "actionable" and not positives:
            skipped["actionable_without_positive_bbox"] += 1
            continue
        if screen["screen_state"] in {"waiting", "returned_to_game"} and positives:
            skipped["non_actionable_with_positive_bbox"] += 1
            continue

        copied += 1
        suffix = source.suffix.lower() or ".png"
        image_name = f"ads_det_{copied:06d}{suffix}"
        image_path = output_dir / "images" / image_name
        shutil.copy2(source, image_path)
        split_group = f"content:{screen['content_id']}"
        screen_row = {
            "screen_id": f"ads_det_{copied:06d}",
            "image_path": str(image_path),
            "original_path": screen["original_path"],
            "relative_path": screen["relative_path"],
            "instance_id": screen["instance_id"],
            "content_id": screen["content_id"],
            "vision_domain": screen["vision_domain"],
            "screen_state": screen["screen_state"],
            "asset_type": screen["asset_type"],
            "representation": screen["representation"],
            "source_root": screen["source_root"],
            "width": width,
            "height": height,
            "positive_bbox_count": len(positives),
            "split_group": split_group,
            "split": "",
        }
        screen_rows.append(screen_row)
        coco_images.append(
            {
                "id": copied,
                "file_name": f"images/{image_name}",
                "width": width,
                "height": height,
                "instance_id": screen["instance_id"],
                "content_id": screen["content_id"],
                "screen_state": screen["screen_state"],
            }
        )
        for box in positives:
            ann_id += 1
            x, y, w, h = clamp_bbox(box, width, height)
            annotation_rows.append(
                {
                    "annotation_id": f"ann_{ann_id:06d}",
                    "screen_id": screen_row["screen_id"],
                    "image_path": str(image_path),
                    "instance_id": screen["instance_id"],
                    "content_id": screen["content_id"],
                    "bbox_id": box["bbox_id"],
                    "bbox_x": f"{x:.3f}",
                    "bbox_y": f"{y:.3f}",
                    "bbox_w": f"{w:.3f}",
                    "bbox_h": f"{h:.3f}",
                    "category": DETECTOR_CLASS,
                    "label": box["label"],
                    "source_class": box["class_name"],
                    "screen_state": screen["screen_state"],
                    "split_group": split_group,
                    "split": "",
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
                    "bbox_id": box["bbox_id"],
                }
            )

    screen_fields = [
        "screen_id",
        "image_path",
        "original_path",
        "relative_path",
        "instance_id",
        "content_id",
        "vision_domain",
        "screen_state",
        "asset_type",
        "representation",
        "source_root",
        "width",
        "height",
        "positive_bbox_count",
        "split_group",
        "split",
    ]
    annotation_fields = [
        "annotation_id",
        "screen_id",
        "image_path",
        "instance_id",
        "content_id",
        "bbox_id",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "category",
        "label",
        "source_class",
        "screen_state",
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
        "dataset_kind": "ads_detector_fullscreen_bbox",
        "db": str(args.db),
        "domains": args.domains,
        "screens_queried": len(screens),
        "screens_exported": len(screen_rows),
        "annotations_exported": len(annotation_rows),
        "screen_state_counts": dict(Counter(row["screen_state"] for row in screen_rows)),
        "domain_counts": dict(Counter(row["vision_domain"] for row in screen_rows)),
        "representation_counts": dict(Counter(row["representation"] for row in screen_rows)),
        "skipped": dict(skipped),
        "detector_class": DETECTOR_CLASS,
        "note": "This exports a detector dataset only. No learned detector trainer is invoked by this tool.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an Ads detector full-screen bbox dataset from reviewed GUI annotations.")
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/datasets/detector/action_candidate"))
    parser.add_argument("--domains", nargs="+", default=list(DEFAULT_DOMAINS), choices=["ads", "shared"])
    parser.add_argument("--path-contains", default="")
    parser.add_argument("--include-annotated", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    build(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
