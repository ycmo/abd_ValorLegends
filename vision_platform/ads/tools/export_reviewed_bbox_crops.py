from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class ExportRow:
    candidate_id: str
    crop_path: Path
    context_crop_path: Path
    parent_instance_id: str
    parent_content_id: str
    parent_path: str
    parent_relative_path: str
    bbox_id: int
    bbox: tuple[float, float, float, float]
    screen_state: str
    bbox_label: str
    bbox_class: str
    source_session: str
    proposal_source: str
    weak_label: str


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def safe_event_metadata(parent_path: Path) -> dict[str, Any]:
    event_json = parent_path.parent / "event.json"
    if not event_json.exists():
        return {}
    try:
        return json.loads(event_json.read_text(encoding="utf-8"))
    except Exception:
        return {}


def crop_bbox(image: np.ndarray, bbox: tuple[float, float, float, float], *, scale: float = 1.0) -> np.ndarray:
    x, y, w, h = bbox
    side_w = max(1, int(round(w * scale)))
    side_h = max(1, int(round(h * scale)))
    cx = x + w / 2
    cy = y + h / 2
    left = int(round(cx - side_w / 2))
    top = int(round(cy - side_h / 2))
    return crop_with_padding(image, left, top, side_w, side_h)


def crop_with_padding(image: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    height, width = image.shape[:2]
    canvas = np.zeros((h, w, image.shape[2]), dtype=image.dtype)
    src_x1 = max(0, x)
    src_y1 = max(0, y)
    src_x2 = min(width, x + w)
    src_y2 = min(height, y + h)
    if src_x2 <= src_x1 or src_y2 <= src_y1:
        return canvas
    dst_x1 = src_x1 - x
    dst_y1 = src_y1 - y
    canvas[dst_y1 : dst_y1 + (src_y2 - src_y1), dst_x1 : dst_x1 + (src_x2 - src_x1)] = image[src_y1:src_y2, src_x1:src_x2]
    return canvas


def write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    path.write_bytes(encoded.tobytes())


def reviewed_bbox_rows(con: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    clauses = [
        "r.review_status = 'reviewed'",
        "r.screen_state = 'actionable'",
        "a.image_scope = 'fullscreen'",
        "r.vision_domain IN ('ads', 'shared')",
        "b.label = 'positive'",
        "(c.name IS NULL OR c.name = 'action_target')",
    ]
    params: list[Any] = []
    if args.path_contains:
        clauses.append("a.relative_path LIKE ?")
        params.append(f"%{args.path_contains}%")
    if args.filename:
        clauses.append("a.filename = ?")
        params.append(args.filename)
    if args.domain != "all":
        clauses.append("r.vision_domain = ?")
        params.append(args.domain)
    where = " AND ".join(clauses)
    return con.execute(
        f"""
        SELECT
            a.instance_id AS parent_instance_id,
            a.content_id AS parent_content_id,
            a.original_path AS parent_path,
            a.relative_path AS parent_relative_path,
            r.screen_state,
            b.id AS bbox_id,
            b.x,
            b.y,
            b.w,
            b.h,
            b.label AS bbox_label,
            COALESCE(c.name, '') AS bbox_class
        FROM assets a
        JOIN image_reviews r ON r.instance_id = a.instance_id
        JOIN bboxes b ON b.instance_id = a.instance_id
        LEFT JOIN classes c ON c.id = b.class_id
        WHERE {where}
        ORDER BY a.relative_path COLLATE NOCASE, b.id
        """,
        params,
    ).fetchall()


def write_manifest(path: Path, rows: list[ExportRow]) -> None:
    fields = [
        "candidate_id",
        "crop_path",
        "context_crop_path",
        "parent_instance_id",
        "parent_content_id",
        "parent_path",
        "parent_relative_path",
        "bbox_id",
        "bbox",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "screen_state",
        "bbox_label",
        "bbox_class",
        "source_session",
        "proposal_source",
        "weak_label",
        "review_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            x, y, w, h = row.bbox
            writer.writerow(
                {
                    "candidate_id": row.candidate_id,
                    "crop_path": str(row.crop_path.resolve()),
                    "context_crop_path": str(row.context_crop_path.resolve()),
                    "parent_instance_id": row.parent_instance_id,
                    "parent_content_id": row.parent_content_id,
                    "parent_path": row.parent_path,
                    "parent_relative_path": row.parent_relative_path,
                    "bbox_id": row.bbox_id,
                    "bbox": json.dumps([x, y, w, h], ensure_ascii=False),
                    "bbox_x": f"{x:.3f}",
                    "bbox_y": f"{y:.3f}",
                    "bbox_w": f"{w:.3f}",
                    "bbox_h": f"{h:.3f}",
                    "screen_state": row.screen_state,
                    "bbox_label": row.bbox_label,
                    "bbox_class": row.bbox_class,
                    "source_session": row.source_session,
                    "proposal_source": row.proposal_source,
                    "weak_label": row.weak_label,
                    "review_status": "pending_visual_family_review",
                }
            )


def export(args: argparse.Namespace) -> None:
    output_dir: Path = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    crop_dir = output_dir / "crops"
    context_dir = output_dir / "context_1_5x"
    crop_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)

    con = open_db(args.db)
    source_rows = reviewed_bbox_rows(con, args)
    exports: list[ExportRow] = []
    skipped: dict[str, int] = {}
    for index, row in enumerate(source_rows, start=1):
        parent_path = Path(row["parent_path"])
        image = cv2.imdecode(np.fromfile(str(parent_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            skipped["unreadable_parent"] = skipped.get("unreadable_parent", 0) + 1
            continue
        bbox = (float(row["x"]), float(row["y"]), float(row["w"]), float(row["h"]))
        candidate_id = f"rb_{index:06d}"
        crop_path = crop_dir / f"{candidate_id}.png"
        context_crop_path = context_dir / f"{candidate_id}_context_1_5x.png"
        write_png(crop_path, crop_bbox(image, bbox, scale=1.0))
        write_png(context_crop_path, crop_bbox(image, bbox, scale=args.context_scale))
        metadata = safe_event_metadata(parent_path)
        exports.append(
            ExportRow(
                candidate_id=candidate_id,
                crop_path=crop_path,
                context_crop_path=context_crop_path,
                parent_instance_id=row["parent_instance_id"],
                parent_content_id=row["parent_content_id"],
                parent_path=row["parent_path"],
                parent_relative_path=row["parent_relative_path"],
                bbox_id=int(row["bbox_id"]),
                bbox=bbox,
                screen_state=row["screen_state"],
                bbox_label=row["bbox_label"],
                bbox_class=row["bbox_class"],
                source_session=metadata.get("source_session", "") or parent_path.parent.name,
                proposal_source=metadata.get("proposal_source", ""),
                weak_label=metadata.get("weak_label", ""),
            )
        )

    write_manifest(output_dir / "manifest.csv", exports)
    summary = {
        "source_rows": len(source_rows),
        "exported_crops": len(exports),
        "skipped": skipped,
        "db": str(args.db),
        "path_contains": args.path_contains,
        "filename": args.filename,
        "domain": args.domain,
        "output_dir": str(output_dir.resolve()),
        "manifest": str((output_dir / "manifest.csv").resolve()),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    con.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export reviewed fullscreen action-target bboxes as crop assets.")
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/collections/reviewed_bbox_crops"))
    parser.add_argument("--path-contains", default="")
    parser.add_argument("--filename", default="pre_click.png")
    parser.add_argument("--domain", default="all", choices=["all", "ads", "shared"])
    parser.add_argument("--context-scale", type=float, default=1.5)
    parser.add_argument("--overwrite", action="store_true")
    export(parser.parse_args())


if __name__ == "__main__":
    main()
