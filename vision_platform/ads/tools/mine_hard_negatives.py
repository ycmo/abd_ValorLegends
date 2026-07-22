from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads2.core.geometry_close import GeometryCloseSpec, match_geometry_close_rows


@dataclass(frozen=True)
class ScreenRow:
    instance_id: str
    content_id: str
    original_path: Path
    relative_path: str
    source_session: str
    width: int
    height: int


@dataclass(frozen=True)
class BBox:
    x: float
    y: float
    w: float
    h: float


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def reviewed_actionable_screens(con: sqlite3.Connection, *, domain: str) -> list[ScreenRow]:
    rows = con.execute(
        """
        SELECT DISTINCT
            a.instance_id,
            a.content_id,
            a.original_path,
            a.relative_path,
            a.source_root,
            a.width,
            a.height
        FROM assets a
        JOIN image_reviews r ON r.instance_id = a.instance_id
        JOIN bboxes b ON b.instance_id = a.instance_id
        WHERE r.review_status = 'reviewed'
          AND r.screen_state = 'actionable'
          AND a.image_scope = 'fullscreen'
          AND r.vision_domain IN ('ads', 'shared')
          AND (? = 'all' OR r.vision_domain = ?)
        ORDER BY a.relative_path COLLATE NOCASE
        """,
        (domain, domain),
    ).fetchall()
    return [
        ScreenRow(
            instance_id=row["instance_id"],
            content_id=row["content_id"],
            original_path=Path(row["original_path"]),
            relative_path=row["relative_path"],
            source_session=row["source_root"] or row["content_id"],
            width=int(row["width"] or 0),
            height=int(row["height"] or 0),
        )
        for row in rows
    ]


def positive_bboxes(con: sqlite3.Connection, instance_id: str) -> list[BBox]:
    rows = con.execute(
        """
        SELECT b.x, b.y, b.w, b.h
        FROM bboxes b
        LEFT JOIN classes c ON c.id = b.class_id
        WHERE b.instance_id = ?
          AND b.label = 'positive'
          AND (c.name IS NULL OR c.name = 'action_target')
        """,
        (instance_id,),
    ).fetchall()
    return [BBox(float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"])) for r in rows]


def iou(a: tuple[int, int, int, int], b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b.x, b.y, b.w, b.h
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def center_inside(candidate: tuple[int, int, int, int], box: BBox, *, pad: float = 0.0) -> bool:
    x, y, w, h = candidate
    cx = x + w / 2
    cy = y + h / 2
    return (box.x - pad) <= cx <= (box.x + box.w + pad) and (box.y - pad) <= cy <= (box.y + box.h + pad)


def crop_bbox(screen: np.ndarray, bbox: tuple[int, int, int, int], *, scale: float = 1.5, output_size: int = 96) -> Image.Image:
    x, y, w, h = bbox
    side = max(1, int(round(max(w, h) * scale)))
    cx = x + w / 2
    cy = y + h / 2
    left = int(round(cx - side / 2))
    top = int(round(cy - side / 2))
    patch = crop_with_padding(screen, left, top, side, side)
    rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    return canonical_object(image, output_size=output_size, object_ratio=0.70)


def crop_with_padding(screen: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    height, width = screen.shape[:2]
    canvas = np.zeros((h, w, screen.shape[2]), dtype=screen.dtype)
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


def canonical_object(image: Image.Image, *, output_size: int, object_ratio: float) -> Image.Image:
    image = image.convert("RGB")
    target_max = max(1, round(output_size * object_ratio))
    scale = target_max / max(image.width, image.height)
    new_w = max(1, round(image.width * scale))
    new_h = max(1, round(image.height * scale))
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (output_size, output_size), (0, 0, 0))
    canvas.paste(resized, ((output_size - new_w) // 2, (output_size - new_h) // 2))
    return canvas


def make_contact_sheet(rows: list[dict[str, Any]], output_path: Path) -> None:
    if not rows:
        return
    thumb_w, thumb_h, label_h = 150, 130, 58
    cols = 6
    page_rows = (len(rows) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, page_rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for idx, row in enumerate(rows):
        col = idx % cols
        page_row = idx // cols
        x = col * thumb_w
        y = page_row * (thumb_h + label_h)
        image = Image.open(row["crop_path"]).convert("RGB")
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(image, (x + (thumb_w - image.width) // 2, y + (thumb_h - image.height) // 2))
        text = f"{idx+1:03d} score {row['proposal_score']:.3f}\n{Path(row['source_screen']).name}\n{row['bbox']}"
        draw.text((x + 3, y + thumb_h + 2), text, fill=(0, 0, 0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "candidate_id",
        "crop_path",
        "source_screen",
        "source_instance_id",
        "source_content_id",
        "source_session",
        "bbox",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "proposal_source",
        "proposal_score",
        "initial_label",
        "review_status",
        "max_iou_positive",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def mine(args: argparse.Namespace) -> int:
    con = open_db(args.db)
    screens = reviewed_actionable_screens(con, domain=args.domain)
    output_dir = args.output_dir or Path("vision_platform/ads/hard_negative_mining") / time.strftime("batch_%Y%m%d_%H%M%S")
    crop_dir = output_dir / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)

    scan_scale = max(0.1, min(1.0, float(args.scan_scale)))
    spec = GeometryCloseSpec(
        threshold=args.threshold,
        roi_top_ratio=args.roi_top_ratio,
        max_results=args.max_candidates_per_screen,
        min_size=max(4, int(round(10 * scan_scale))),
        max_size=max(8, int(round(args.max_size * scan_scale))),
        min_axis_union=0.55,
        min_axis_balance=0.25,
        min_length_ratio=0.80,
        max_fill=0.60,
        gates=("white_strict", "white_soft", "black_strict", "black_soft", "cyan_strict", "bright"),
        two_stroke_fit=True,
        max_fit_error=0.42,
        max_extra_error=0.055,
        max_missing_error=0.80,
        max_center_extra_error=0.035,
        dedupe_distance=10,
    )

    rows: list[dict[str, Any]] = []
    scanned = 0
    skipped_positive_overlap = 0
    for screen_row in screens[: args.max_screens if args.max_screens > 0 else None]:
        positives = positive_bboxes(con, screen_row.instance_id)
        if not positives:
            continue
        image = cv2.imdecode(np.fromfile(str(screen_row.original_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        scanned += 1
        scan_image = image
        if scan_scale != 1.0:
            scan_image = cv2.resize(
                image,
                (max(1, int(round(image.shape[1] * scan_scale))), max(1, int(round(image.shape[0] * scan_scale)))),
                interpolation=cv2.INTER_AREA,
            )
        proposals = match_geometry_close_rows(scan_image, spec=spec)
        for proposal in proposals:
            raw_bbox = tuple(int(v) for v in proposal["bbox"])
            if scan_scale != 1.0:
                sx, sy, sw, sh = raw_bbox
                bbox = (
                    int(round(sx / scan_scale)),
                    int(round(sy / scan_scale)),
                    max(1, int(round(sw / scan_scale))),
                    max(1, int(round(sh / scan_scale))),
                )
            else:
                bbox = raw_bbox
            max_iou = max((iou(bbox, box) for box in positives), default=0.0)
            if max_iou >= args.exclude_iou or any(center_inside(bbox, box, pad=args.exclude_center_pad) for box in positives):
                skipped_positive_overlap += 1
                continue
            candidate_id = f"hn_{len(rows)+1:06d}"
            crop_path = crop_dir / f"{candidate_id}.png"
            crop_bbox(image, bbox, scale=args.crop_scale, output_size=args.output_size).save(crop_path)
            x, y, w, h = bbox
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "crop_path": str(crop_path.resolve()),
                    "source_screen": str(screen_row.original_path.resolve()),
                    "source_instance_id": screen_row.instance_id,
                    "source_content_id": screen_row.content_id,
                    "source_session": screen_row.source_session,
                    "bbox": json.dumps(list(bbox), ensure_ascii=False),
                    "bbox_x": x,
                    "bbox_y": y,
                    "bbox_w": w,
                    "bbox_h": h,
                    "proposal_source": "geometry_close_hard_negative",
                    "proposal_score": float(proposal.get("score", 0.0)),
                    "initial_label": "pending_non_action_candidate",
                    "review_status": "pending",
                    "max_iou_positive": f"{max_iou:.4f}",
                }
            )
            if len(rows) >= args.max_total:
                break
        if len(rows) >= args.max_total:
            break

    rows.sort(key=lambda row: float(row["proposal_score"]), reverse=True)
    write_manifest(output_dir / "manifest.csv", rows)
    make_contact_sheet(rows[: args.contact_sheet_limit], output_dir / "contact_sheet.png")
    summary = {
        "scanned_screens": scanned,
        "reviewed_actionable_screens": len(screens),
        "candidates_exported": len(rows),
        "skipped_positive_overlap": skipped_positive_overlap,
        "threshold": args.threshold,
        "scan_scale": scan_scale,
        "max_screens": args.max_screens,
        "exclude_iou": args.exclude_iou,
        "exclude_center_pad": args.exclude_center_pad,
        "output_dir": str(output_dir.resolve()),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    con.close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine pending classifier hard negatives from reviewed fullscreen ads screens.")
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--domain", default="all", choices=["all", "ads", "shared"])
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--roi-top-ratio", type=float, default=1.0)
    parser.add_argument("--max-candidates-per-screen", type=int, default=20)
    parser.add_argument("--max-screens", type=int, default=80, help="Limit scanned fullscreen images. 0 means all.")
    parser.add_argument("--scan-scale", type=float, default=0.5, help="Downscale fullscreen images before proposal scan for speed.")
    parser.add_argument("--max-total", type=int, default=500)
    parser.add_argument("--max-size", type=int, default=64)
    parser.add_argument("--exclude-iou", type=float, default=0.05)
    parser.add_argument("--exclude-center-pad", type=float, default=4.0)
    parser.add_argument("--crop-scale", type=float, default=1.5)
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--contact-sheet-limit", type=int, default=120)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(mine(parse_args()))
