from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


DEFAULT_BBOX_CSV = Path(
    "vision_platform/ads/pilot/visual_family_smoke_20260719/"
    "next_tight_bbox/next_tight_bbox.csv"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def parse_bbox(row: dict[str, str]) -> tuple[int, int, int, int]:
    return tuple(int(float(row[key])) for key in ("x", "y", "w", "h"))  # type: ignore[return-value]


def jitter_image(image: Image.Image, rng: random.Random) -> Image.Image:
    image = image.convert("RGB")
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.9, 1.12))
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.9, 1.15))
    if rng.random() < 0.18:
        image = image.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.1, 0.35)))
    if rng.random() < 0.2:
        image = ImageOps.autocontrast(image, cutoff=rng.uniform(0.0, 0.6))
    return image


def recrop_context(source: Image.Image, bbox: tuple[int, int, int, int], rng: random.Random) -> Image.Image:
    x, y, w, h = bbox
    source = source.convert("RGB")
    bbox_cx = x + w / 2.0
    bbox_cy = y + h / 2.0

    # Pick a square crop inside the original 96x96 image. It must contain the tight bbox.
    min_side = max(w, h) + 2
    max_side = min(source.width, source.height)
    # Bias toward realistic contexts: sometimes tight, often close to the original crop.
    side = round(rng.triangular(min_side, max_side, max_side * 0.75))
    side = max(min_side, min(max_side, side))

    left_min = max(0, x + w - side)
    left_max = min(x, source.width - side)
    top_min = max(0, y + h - side)
    top_max = min(y, source.height - side)
    if left_min > left_max:
        left = round(max(0, min(source.width - side, bbox_cx - side / 2)))
    else:
        left = rng.randint(round(left_min), round(left_max))
    if top_min > top_max:
        top = round(max(0, min(source.height - side, bbox_cy - side / 2)))
    else:
        top = rng.randint(round(top_min), round(top_max))

    crop = source.crop((left, top, left + side, top + side))
    crop = jitter_image(crop, rng)
    return crop.resize((96, 96), Image.Resampling.BILINEAR)


def make_contact_sheet(paths: list[Path], output: Path, max_items: int = 80) -> None:
    if not paths:
        return
    from PIL import ImageDraw, ImageFont

    paths = paths[:max_items]
    cols, thumb, label_h, pad = 8, 96, 18, 8
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, path in enumerate(paths):
        x = pad + (index % cols) * (thumb + pad)
        y = pad + (index // cols) * (thumb + label_h + pad)
        image = Image.open(path).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        sheet.paste(image, (x, y))
        draw.text((x, y + thumb + 2), path.stem[-12:], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate train-only Next context recrops from tight bboxes.")
    parser.add_argument("--assigned-manifest", type=Path, required=True)
    parser.add_argument("--bbox-csv", type=Path, default=DEFAULT_BBOX_CSV)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples-per-source", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise SystemExit(f"output dir exists and is not empty: {args.output_dir}; pass --overwrite")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = args.output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = read_csv(args.assigned_manifest)
    bbox_rows = {
        row["instance_id"]: row
        for row in read_csv(args.bbox_csv)
        if row.get("instance_id") and row.get("x") and row.get("y") and row.get("w") and row.get("h")
    }
    train_next_rows = [
        row
        for row in manifest_rows
        if row.get("split") == "train" and row.get("families") == "next" and row.get("instance_id") in bbox_rows
    ]
    if not train_next_rows:
        raise SystemExit("No train split next rows with tight bbox found.")

    rng = random.Random(args.seed)
    fieldnames = list(manifest_rows[0].keys())
    synthetic_rows: list[dict[str, str]] = []
    synthetic_paths: list[Path] = []
    for row in train_next_rows:
        source = Image.open(row["image_path"]).convert("RGB")
        bbox = parse_bbox(bbox_rows[row["instance_id"]])
        for index in range(args.samples_per_source):
            synthetic_key = f"{row['instance_id']}:context_recrop:{args.seed}:{index}"
            instance_id = f"file_synth_next_ctx_{sha16(synthetic_key)}"
            content_id = f"asset_synth_next_ctx_{sha16('content:' + synthetic_key)}"
            image_name = f"synth_next_ctx_{row['instance_id']}_{index:03d}.png"
            image_path = images_dir / image_name
            image = recrop_context(source, bbox, rng)
            image.save(image_path)
            new_row = dict(row)
            new_row.update(
                {
                    "image_path": str(image_path),
                    "families": "next",
                    "label_x_mark": "0",
                    "label_play_triangle": "0",
                    "label_google_play": "0",
                    "label_next": "1",
                    "label_free": "0",
                    "label_got": "0",
                    "label_arrow": "0",
                    "split": "train",
                    "group_key": f"synthetic_next_context:{row['instance_id']}",
                    "instance_id": instance_id,
                    "content_id": content_id,
                    "review_status": "synthetic",
                    "source_root": "synthetic_next_context_recrop",
                    "pool_status": "trainable",
                    "pool_role": "synthetic_next_context_train_only",
                    "is_none_of_the_above": "0",
                    "is_confirmed_strong_hard_negative": "0",
                    "evaluation_status": "synthetic_train_only_not_for_eval",
                }
            )
            synthetic_rows.append(new_row)
            synthetic_paths.append(image_path)

    for row in synthetic_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    combined_rows = [*manifest_rows, *synthetic_rows]
    write_csv(args.output_dir / "manifest.csv", combined_rows, fieldnames)
    write_csv(args.output_dir / "synthetic_rows.csv", synthetic_rows, fieldnames)
    make_contact_sheet(synthetic_paths, args.output_dir / "synthetic_next_context_contact_sheet.png")

    summary = {
        "assigned_manifest": str(args.assigned_manifest),
        "bbox_csv": str(args.bbox_csv),
        "output_dir": str(args.output_dir),
        "seed": args.seed,
        "samples_per_source": args.samples_per_source,
        "train_next_sources": len(train_next_rows),
        "synthetic_rows": len(synthetic_rows),
        "total_rows": len(combined_rows),
        "manifest": str(args.output_dir / "manifest.csv"),
        "contact_sheet": str(args.output_dir / "synthetic_next_context_contact_sheet.png"),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
