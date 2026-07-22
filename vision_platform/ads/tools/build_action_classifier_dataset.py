from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


TRAIN_ROLES = {
    "action_target": "close",
    "non_action_target": "not_close",
}
TRAIN_DOMAINS = {"ads", "shared"}
EXCLUDED_REPRESENTATIONS = {"edge_glyph", "binary_mask", "debug_overlay", "annotated"}


@dataclass
class DatasetRow:
    instance_id: str
    content_id: str
    original_path: str
    relative_path: str
    filename: str
    source_root: str
    asset_role: str
    image_scope: str
    vision_domain: str
    asset_type: str
    representation: str
    sample_role: str
    sub_role: str
    label: str
    output_path: Path
    source_session: str
    source_screen: str


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


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


def source_screen_from_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if "click_success" in relative_path:
        for part in parts:
            if part.startswith("click_success_"):
                return part
    if "hard_negative_mining" in relative_path:
        for i, part in enumerate(parts):
            if part == "hard_negative_mining" and i + 1 < len(parts):
                return parts[i + 1]
    parent = str(Path(relative_path).parent).replace("\\", "/")
    return parent or relative_path


def read_rows(con: sqlite3.Connection, output_dir: Path) -> tuple[list[DatasetRow], Counter]:
    rows = []
    skipped: Counter = Counter()
    query = """
        SELECT
            a.instance_id,
            a.content_id,
            a.original_path,
            a.relative_path,
            a.filename,
            COALESCE(a.source_root, '') AS source_root,
            COALESCE(a.asset_role, '') AS asset_role,
            COALESCE(a.image_scope, '') AS image_scope,
            r.vision_domain,
            r.asset_type,
            r.representation,
            r.sample_role,
            COALESCE(r.sub_role, '') AS sub_role,
            r.review_status
        FROM image_reviews r
        JOIN assets a ON a.instance_id = r.instance_id
        ORDER BY r.vision_domain, r.sample_role, a.relative_path
    """
    images_dir = output_dir / "images"
    index = 0
    for raw in con.execute(query):
        if raw["review_status"] != "reviewed":
            skipped["not_reviewed"] += 1
            continue
        if raw["vision_domain"] not in TRAIN_DOMAINS:
            skipped[f"domain:{raw['vision_domain']}"] += 1
            continue
        if raw["sample_role"] not in TRAIN_ROLES:
            skipped[f"role:{raw['sample_role']}"] += 1
            continue
        if raw["image_scope"] != "crop":
            skipped[f"scope:{raw['image_scope']}"] += 1
            continue
        if raw["representation"] in EXCLUDED_REPRESENTATIONS:
            skipped[f"representation:{raw['representation']}"] += 1
            continue
        source = Path(raw["original_path"])
        if not source.exists():
            skipped["missing_file"] += 1
            continue

        label = TRAIN_ROLES[raw["sample_role"]]
        index += 1
        safe_content = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw["content_id"])[:32]
        output_name = f"ads_action_v2_{index:05d}_{label}_{safe_content}.png"
        source_screen = source_screen_from_path(raw["relative_path"])
        rows.append(
            DatasetRow(
                instance_id=raw["instance_id"],
                content_id=raw["content_id"],
                original_path=raw["original_path"],
                relative_path=raw["relative_path"],
                filename=raw["filename"],
                source_root=raw["source_root"],
                asset_role=raw["asset_role"],
                image_scope=raw["image_scope"],
                vision_domain=raw["vision_domain"],
                asset_type=raw["asset_type"],
                representation=raw["representation"],
                sample_role=raw["sample_role"],
                sub_role=raw["sub_role"],
                label=label,
                output_path=images_dir / output_name,
                source_session=raw["content_id"],
                source_screen=source_screen,
            )
        )
    return rows, skipped


def write_manifest(rows: list[DatasetRow], output: Path) -> None:
    fields = [
        "image_path",
        "label",
        "review_status",
        "source_screen",
        "source_session",
        "ad_source",
        "icon_family",
        "reject_type",
        "candidate_score",
        "geometry_score",
        "bbox",
        "split",
        "instance_id",
        "content_id",
        "original_path",
        "relative_path",
        "vision_domain",
        "asset_type",
        "asset_role",
        "representation",
        "sample_role",
        "sub_role",
    ]
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "image_path": str(row.output_path),
                    "label": row.label,
                    "review_status": "reviewed",
                    "source_screen": row.source_screen,
                    "source_session": row.source_session,
                    "ad_source": row.source_root,
                    "icon_family": row.sub_role or row.asset_role,
                    "reject_type": row.sample_role,
                    "candidate_score": "",
                    "geometry_score": "",
                    "bbox": "",
                    "split": "",
                    "instance_id": row.instance_id,
                    "content_id": row.content_id,
                    "original_path": row.original_path,
                    "relative_path": row.relative_path,
                    "vision_domain": row.vision_domain,
                    "asset_type": row.asset_type,
                    "asset_role": row.asset_role,
                    "representation": row.representation,
                    "sample_role": row.sample_role,
                    "sub_role": row.sub_role,
                }
            )


def write_contact_sheet(rows: list[DatasetRow], output: Path, max_items: int = 120) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    items = rows[:max_items]
    cols, thumb, label_h, pad = 8, 96, 34, 8
    rows_n = max(1, (len(items) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, item in enumerate(items):
        x = pad + (i % cols) * (thumb + pad)
        y = pad + (i // cols) * (thumb + label_h + pad)
        try:
            img = Image.open(item.output_path).convert("RGB")
        except Exception:
            img = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(img.resize((thumb, thumb), Image.Resampling.NEAREST), (x, y))
        color = (0, 110, 40) if item.label == "close" else (150, 30, 30)
        draw.text((x, y + thumb + 2), item.label, fill=color, font=font)
        draw.text((x, y + thumb + 16), item.source_root[:18], fill=(20, 20, 20), font=font)
    sheet.save(output)


def build_dataset(args: argparse.Namespace) -> None:
    output_dir: Path = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)

    con = connect(args.db)
    rows, skipped = read_rows(con, output_dir)
    if not rows:
        raise SystemExit("no trainable rows found")

    for row in rows:
        with Image.open(row.original_path) as image:
            canonical_object(image, args.output_size, args.object_ratio).save(row.output_path)

    write_manifest(rows, output_dir / "manifest.csv")
    label_counts = Counter(row.label for row in rows)
    summary = {
        "rows": len(rows),
        "label_counts": dict(label_counts),
        "domain_counts": dict(Counter(row.vision_domain for row in rows)),
        "asset_role_counts": dict(Counter(row.asset_role for row in rows)),
        "source_root_counts": dict(Counter(row.source_root for row in rows)),
        "unique_content_ids": len({row.content_id for row in rows}),
        "skipped": dict(skipped),
        "output_size": args.output_size,
        "object_ratio": args.object_ratio,
        "manifest": str(output_dir / "manifest.csv"),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_contact_sheet(rows, output_dir / "contact_sheet.png")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/action_classifier_v2/dataset"))
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--object-ratio", type=float, default=0.70)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    build_dataset(args)


if __name__ == "__main__":
    main()
