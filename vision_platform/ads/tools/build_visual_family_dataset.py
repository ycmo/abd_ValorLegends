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


FAMILIES = [
    "x_mark",
    "play_triangle",
    "google_play",
    "next",
    "free",
    "got",
    "arrow",
]
NEGATIVE_FAMILY = "negative"
TRAIN_DOMAINS = {"ads", "shared"}
EXCLUDED_REPRESENTATIONS = {"edge_glyph", "binary_mask", "debug_overlay", "annotated", "grayscale"}
EXCLUDED_FAMILIES = {"uncertain", "other"}
FAMILY_PARENT_MAP = {
    "double_triangle": "play_triangle",
    "single_chevron": "arrow",
    "double_chevron": "arrow",
    "double_chevron_text": "arrow",
    "back_arrow": "arrow",
    "next_button": "next",
    "arrow_other": "arrow",
}


@dataclass
class DatasetRow:
    instance_id: str
    content_id: str
    original_path: str
    relative_path: str
    source_root: str
    asset_role: str
    image_scope: str
    vision_domain: str
    asset_type: str
    representation: str
    families: list[str]
    output_path: Path
    source_screen: str
    group_key: str


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
    for part in parts:
        if part.startswith("click_success_"):
            return part
    if "hard_negative_mining" in relative_path:
        # Current mined crops do not retain parent screen ids, so avoid grouping the
        # whole batch together. Content id still prevents exact duplicate leakage.
        return ""
    parent = str(Path(relative_path).parent).replace("\\", "/")
    return parent or relative_path


def group_key_for(row: sqlite3.Row) -> str:
    # For this first crop-level family smoke test, exact content leakage is the
    # primary risk. Grouping all templates by parent folder makes small families
    # such as google_play impossible to split, so use content_id as the stable
    # baseline group. Parent screen/session can be reintroduced when we have
    # more positives per family.
    return f"content:{row['content_id']}"


def read_rows(con: sqlite3.Connection, output_dir: Path) -> tuple[list[DatasetRow], Counter]:
    skipped: Counter = Counter()
    rows: list[DatasetRow] = []
    query = """
        SELECT
            v.instance_id,
            v.families,
            v.review_status AS visual_review_status,
            a.content_id,
            a.original_path,
            a.relative_path,
            COALESCE(a.source_root, '') AS source_root,
            COALESCE(a.asset_role, '') AS asset_role,
            COALESCE(a.image_scope, '') AS image_scope,
            COALESCE(a.vision_domain, 'unknown') AS vision_domain,
            COALESCE(r.asset_type, '') AS asset_type,
            COALESCE(r.representation, 'unknown') AS representation
        FROM visual_family_reviews v
        JOIN assets a ON a.instance_id = v.instance_id
        LEFT JOIN image_reviews r ON r.instance_id = v.instance_id
        ORDER BY a.relative_path COLLATE NOCASE
    """
    index = 0
    for raw in con.execute(query):
        if raw["visual_review_status"] != "reviewed":
            skipped["not_visual_reviewed"] += 1
            continue
        if raw["vision_domain"] not in TRAIN_DOMAINS:
            skipped[f"domain:{raw['vision_domain']}"] += 1
            continue
        if raw["image_scope"] != "crop":
            skipped[f"scope:{raw['image_scope']}"] += 1
            continue
        if raw["representation"] in EXCLUDED_REPRESENTATIONS:
            skipped[f"representation:{raw['representation']}"] += 1
            continue
        family_set = {item for item in (raw["families"] or "").split("|") if item}
        if not family_set:
            skipped["empty_family"] += 1
            continue
        if family_set <= EXCLUDED_FAMILIES:
            skipped["only_excluded_family"] += 1
            continue
        mapped_family_set = {FAMILY_PARENT_MAP.get(item, item) for item in family_set}
        if NEGATIVE_FAMILY in mapped_family_set:
            # Negative remains a human review label, but it is not a model head.
            # Keep the row as a none-of-the-above sample with all official
            # family labels set to 0.
            dataset_families = [NEGATIVE_FAMILY]
        else:
            dataset_families = sorted(mapped_family_set & set(FAMILIES))
        if not dataset_families:
            skipped["no_train_family"] += 1
            continue
        source = Path(raw["original_path"])
        if not source.exists():
            skipped["missing_file"] += 1
            continue
        index += 1
        label_text = "+".join(dataset_families)
        safe_content = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw["content_id"])[:32]
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label_text)[:48]
        output_path = output_dir / "images" / f"vf_{index:05d}_{safe_label}_{safe_content}.png"
        rows.append(
            DatasetRow(
                instance_id=raw["instance_id"],
                content_id=raw["content_id"],
                original_path=raw["original_path"],
                relative_path=raw["relative_path"],
                source_root=raw["source_root"],
                asset_role=raw["asset_role"],
                image_scope=raw["image_scope"],
                vision_domain=raw["vision_domain"],
                asset_type=raw["asset_type"],
                representation=raw["representation"],
                families=dataset_families,
                output_path=output_path,
                source_screen=source_screen_from_path(raw["relative_path"]),
                group_key=group_key_for(raw),
            )
        )
    return rows, skipped


def write_manifest(rows: list[DatasetRow], output: Path) -> None:
    fields = [
        "image_path",
        "families",
        *[f"label_{family}" for family in FAMILIES],
        "review_status",
        "group_key",
        "source_screen",
        "instance_id",
        "content_id",
        "original_path",
        "relative_path",
        "vision_domain",
        "asset_type",
        "asset_role",
        "image_scope",
        "representation",
        "source_root",
        "split",
    ]
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            family_set = set(row.families)
            writer.writerow(
                {
                    "image_path": str(row.output_path),
                    "families": "|".join(row.families),
                    **{f"label_{family}": int(family in family_set) for family in FAMILIES},
                    "review_status": "reviewed",
                    "group_key": row.group_key,
                    "source_screen": row.source_screen,
                    "instance_id": row.instance_id,
                    "content_id": row.content_id,
                    "original_path": row.original_path,
                    "relative_path": row.relative_path,
                    "vision_domain": row.vision_domain,
                    "asset_type": row.asset_type,
                    "asset_role": row.asset_role,
                    "image_scope": row.image_scope,
                    "representation": row.representation,
                    "source_root": row.source_root,
                    "split": "",
                }
            )


def write_contact_sheet(rows: list[DatasetRow], output: Path, max_items: int = 160) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    items = rows[:max_items]
    cols, thumb, label_h, pad = 8, 96, 38, 8
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
        text = "+".join(item.families)
        draw.text((x, y + thumb + 2), text[:18], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 18), item.source_root[:18], fill=(80, 80, 80), font=font)
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
        raise SystemExit("no visual-family rows found")

    for row in rows:
        with Image.open(row.original_path) as image:
            canonical_object(image, args.output_size, args.object_ratio).save(row.output_path)

    write_manifest(rows, output_dir / "manifest.csv")
    family_counts = Counter(family for row in rows for family in row.families)
    official_label_counts = Counter(family for row in rows for family in (set(row.families) & set(FAMILIES)))
    combo_counts = Counter("|".join(row.families) for row in rows)
    summary = {
        "rows": len(rows),
        "families": FAMILIES,
        "family_counts": dict(family_counts),
        "official_label_counts": dict(official_label_counts),
        "none_of_the_above_rows": sum(1 for row in rows if not (set(row.families) & set(FAMILIES))),
        "combo_counts": dict(combo_counts),
        "domain_counts": dict(Counter(row.vision_domain for row in rows)),
        "asset_role_counts": dict(Counter(row.asset_role for row in rows)),
        "source_root_counts": dict(Counter(row.source_root for row in rows)),
        "representation_counts": dict(Counter(row.representation for row in rows)),
        "unique_content_ids": len({row.content_id for row in rows}),
        "unique_groups": len({row.group_key for row in rows}),
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
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/dataset"))
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--object-ratio", type=float, default=0.70)
    parser.add_argument("--overwrite", action="store_true")
    build_dataset(parser.parse_args())


if __name__ == "__main__":
    main()
