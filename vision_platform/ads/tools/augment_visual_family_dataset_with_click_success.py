from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from build_visual_family_dataset import FAMILIES, canonical_object


WEAK_FAMILY_BY_PROPOSAL_SOURCE = {
    "free_ad_template": "free",
    "got_template": "got",
    "google_play_template": "google_play",
    "next_template": "next",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_id_for(path: Path) -> str:
    return f"asset_{sha256_file(path)[:16]}"


def weak_family_for(row: dict[str, str]) -> str:
    proposal_source = row.get("proposal_source", "")
    template_name = Path(row.get("template_name", "")).name.lower()
    if proposal_source == "close_template":
        if template_name == "close_11.png":
            return "arrow"
        return "x_mark"
    return WEAK_FAMILY_BY_PROPOSAL_SOURCE.get(proposal_source, "")


def safe_text(value: str, limit: int = 48) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value)[:limit].strip("_") or "unknown"


def asset_for_path(con: sqlite3.Connection, original_path: Path) -> sqlite3.Row | None:
    resolved = str(original_path.resolve())
    return con.execute(
        """
        SELECT instance_id, content_id, relative_path, source_root, asset_role, image_scope, vision_domain
        FROM assets
        WHERE original_path = ?
        """,
        (resolved,),
    ).fetchone()


def reviewed_family_for_instance(con: sqlite3.Connection, instance_id: str) -> str:
    row = con.execute(
        "SELECT families FROM visual_family_reviews WHERE instance_id = ? AND review_status = 'reviewed'",
        (instance_id,),
    ).fetchone()
    return str(row["families"] or "") if row else ""


def copy_base_dataset(base_manifest: Path, output_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows = read_csv(base_manifest)
    fields = list(rows[0].keys()) if rows else []
    for row in rows:
        src = Path(row["image_path"])
        dst = output_dir / "images" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        row["image_path"] = str(dst)
        row.setdefault("label_source", "human_review")
        row.setdefault("weak_label_rule", "")
        row.setdefault("event_id", "")
        row.setdefault("proposal_source", "")
        row.setdefault("template_name", "")
        row.setdefault("bbox_crop", "")
        row.setdefault("event_dir", "")
    return rows, fields


def add_weak_rows(
    *,
    rows: list[dict[str, Any]],
    fields: list[str],
    predictions_csv: Path,
    output_dir: Path,
    db: Path,
    output_size: int,
    object_ratio: float,
) -> dict[str, Any]:
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    existing_instances = {row.get("instance_id", "") for row in rows}
    existing_content_ids = {row.get("content_id", "") for row in rows}
    skipped: Counter[str] = Counter()
    added: list[dict[str, Any]] = []

    index = len(rows)
    for source_row in read_csv(predictions_csv):
        family = weak_family_for(source_row)
        if not family:
            skipped["unsupported_proposal_source"] += 1
            continue
        if family not in FAMILIES:
            skipped["unknown_family"] += 1
            continue
        crop = Path(source_row.get("bbox_crop", ""))
        if not crop.exists():
            skipped["missing_bbox_crop"] += 1
            continue
        asset = asset_for_path(con, crop)
        if asset is not None:
            instance_id = asset["instance_id"]
            content_id = asset["content_id"]
            relative_path = asset["relative_path"]
            source_root = asset["source_root"]
            asset_role = asset["asset_role"]
            image_scope = asset["image_scope"]
            vision_domain = asset["vision_domain"]
            reviewed_family = reviewed_family_for_instance(con, instance_id)
            if instance_id in existing_instances or reviewed_family:
                skipped["already_human_reviewed_or_in_base"] += 1
                continue
        else:
            instance_id = f"weak_click_success_{safe_text(source_row.get('event_id', crop.stem), 64)}"
            content_id = content_id_for(crop)
            relative_path = str(crop)
            source_root = "vision_platform/ads/runtime_collection"
            asset_role = "runtime_collection"
            image_scope = "crop"
            vision_domain = "ads"
            if content_id in existing_content_ids:
                skipped["content_already_in_base"] += 1
                continue

        index += 1
        label_text = family
        safe_content = safe_text(content_id, 32)
        output_path = output_dir / "images" / f"vf_{index:05d}_{safe_text(label_text)}_{safe_content}_weak_click_success.png"
        with Image.open(crop) as image:
            canonical_object(image, output_size, object_ratio).save(output_path)

        out: dict[str, Any] = {
            "image_path": str(output_path),
            "families": family,
            **{f"label_{item}": int(item == family) for item in FAMILIES},
            "review_status": "weak_click_success",
            "group_key": f"click_success:{source_row.get('source_session') or source_row.get('event_id') or content_id}",
            "source_screen": source_row.get("pre_click", ""),
            "instance_id": instance_id,
            "content_id": content_id,
            "original_path": str(crop.resolve()),
            "relative_path": relative_path,
            "vision_domain": vision_domain,
            "asset_type": "runtime_crop",
            "asset_role": asset_role,
            "image_scope": image_scope,
            "representation": "raw",
            "source_root": source_root,
            "split": "",
            "label_source": "weak_click_success",
            "weak_label_rule": f"{source_row.get('proposal_source')}:{Path(source_row.get('template_name', '')).name}->{family}",
            "event_id": source_row.get("event_id", ""),
            "proposal_source": source_row.get("proposal_source", ""),
            "template_name": source_row.get("template_name", ""),
            "bbox_crop": str(crop.resolve()),
            "event_dir": source_row.get("event_dir", ""),
        }
        rows.append(out)
        added.append(out)
        existing_instances.add(instance_id)
        existing_content_ids.add(content_id)

    con.close()
    if not fields:
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
    for field in ["label_source", "weak_label_rule", "event_id", "proposal_source", "template_name", "bbox_crop", "event_dir"]:
        if field not in fields:
            fields.append(field)
    return {
        "added_rows": len(added),
        "added_family_counts": dict(Counter(row["families"] for row in added)),
        "skipped": dict(skipped),
        "fields": fields,
    }


def write_contact_sheet(rows: list[dict[str, Any]], output: Path, max_items: int = 160) -> None:
    items = rows[:max_items]
    cols, thumb, label_h, pad = 8, 96, 48, 8
    rows_n = max(1, (len(items) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, item in enumerate(items):
        x = pad + (i % cols) * (thumb + pad)
        y = pad + (i // cols) * (thumb + label_h + pad)
        try:
            img = Image.open(item["image_path"]).convert("RGB")
        except Exception:
            img = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(img.resize((thumb, thumb), Image.Resampling.NEAREST), (x, y))
        draw.text((x, y + thumb + 2), str(item.get("families", ""))[:18], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 18), str(item.get("label_source", ""))[:20], fill=(80, 80, 80), font=font)
        draw.text((x, y + thumb + 34), str(item.get("template_name", ""))[:20], fill=(80, 80, 80), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Append weak click-success labels to an Ads visual-family dataset.")
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--click-success-predictions", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--object-ratio", type=float, default=0.70)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {args.output_dir}")
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows, fields = copy_base_dataset(args.base_manifest, args.output_dir)
    before_rows = len(rows)
    result = add_weak_rows(
        rows=rows,
        fields=fields,
        predictions_csv=args.click_success_predictions,
        output_dir=args.output_dir,
        db=args.db,
        output_size=args.output_size,
        object_ratio=args.object_ratio,
    )
    fields = result["fields"]
    write_csv(args.output_dir / "manifest.csv", rows, fields)
    weak_rows = [row for row in rows if row.get("label_source") == "weak_click_success"]
    write_contact_sheet(weak_rows, args.output_dir / "weak_click_success_contact_sheet.png")
    summary = {
        "base_manifest": str(args.base_manifest),
        "click_success_predictions": str(args.click_success_predictions),
        "rows_before_weak_append": before_rows,
        "rows_total": len(rows),
        "weak_rows": len(weak_rows),
        "family_counts": dict(Counter(row.get("families", "") for row in rows)),
        "weak_family_counts": result["added_family_counts"],
        "skipped_click_success": result["skipped"],
        "weak_label_rules": {
            "close_template + close_11.png": "arrow",
            "close_template + other templates": "x_mark",
            **WEAK_FAMILY_BY_PROPOSAL_SOURCE,
        },
        "manifest": str(args.output_dir / "manifest.csv"),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
