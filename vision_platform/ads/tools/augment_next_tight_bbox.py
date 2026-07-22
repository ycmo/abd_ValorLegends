from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


FAMILIES = [
    "x_mark",
    "play_triangle",
    "google_play",
    "next",
    "free",
    "got",
    "arrow",
]


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


def clamp_bbox(x: int, y: int, w: int, h: int, image: Image.Image) -> tuple[int, int, int, int]:
    x = max(0, min(image.width - 1, x))
    y = max(0, min(image.height - 1, y))
    w = max(1, min(image.width - x, w))
    h = max(1, min(image.height - y, h))
    return x, y, w, h


def make_background(source: Image.Image, rng: random.Random) -> Image.Image:
    mode = rng.choice(["solid_dark", "solid_gray", "noisy_dark"])
    if mode == "solid_dark":
        value = rng.randint(0, 28)
        return Image.new("RGB", (96, 96), (value, value, value))
    if mode == "solid_gray":
        value = rng.randint(25, 80)
        return Image.new("RGB", (96, 96), (value, value, value))
    value = rng.randint(0, 45)
    background = Image.new("RGB", (96, 96), (value, value, value))
    pixels = background.load()
    for _ in range(rng.randint(20, 120)):
        x = rng.randrange(96)
        y = rng.randrange(96)
        delta = rng.randint(-8, 12)
        current = pixels[x, y][0]
        next_value = max(0, min(95, current + delta))
        pixels[x, y] = (next_value, next_value, next_value)
    return background.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.0, 0.35)))


def augment_object(source: Image.Image, bbox: tuple[int, int, int, int], rng: random.Random) -> Image.Image:
    x, y, w, h = clamp_bbox(*bbox, source)
    pad = rng.choice([0, 1, 2])
    crop_box = (
        max(0, x - pad),
        max(0, y - pad),
        min(source.width, x + w + pad),
        min(source.height, y + h + pad),
    )
    obj = source.crop(crop_box).convert("RGB")

    obj = ImageEnhance.Brightness(obj).enhance(rng.uniform(0.85, 1.18))
    obj = ImageEnhance.Contrast(obj).enhance(rng.uniform(0.85, 1.22))
    if rng.random() < 0.25:
        obj = obj.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.15, 0.45)))

    target_long = rng.randint(20, 72)
    scale = target_long / max(obj.width, obj.height)
    new_w = max(4, round(obj.width * scale))
    new_h = max(4, round(obj.height * scale))
    obj = obj.resize((new_w, new_h), Image.Resampling.BILINEAR)
    if rng.random() < 0.25:
        obj = obj.rotate(rng.uniform(-2.0, 2.0), resample=Image.Resampling.BILINEAR, expand=True)
    return obj


def compose_augmented(source: Image.Image, bbox: tuple[int, int, int, int], rng: random.Random) -> Image.Image:
    canvas = make_background(source, rng)
    obj = augment_object(source, bbox, rng)
    max_x = max(0, canvas.width - obj.width)
    max_y = max(0, canvas.height - obj.height)
    px = rng.randint(4, max(4, max_x - 4)) if max_x > 8 else max_x // 2
    py = rng.randint(28, max(28, max_y - 4)) if max_y > 32 else max_y // 2
    canvas.paste(obj, (px, py))
    if rng.random() < 0.35:
        canvas = ImageOps.autocontrast(canvas, cutoff=rng.uniform(0.0, 1.0))
    return canvas.resize((96, 96), Image.Resampling.BILINEAR)


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
    parser = argparse.ArgumentParser(description="Generate train-only synthetic Next crops from tight bboxes.")
    parser.add_argument("--assigned-manifest", type=Path, required=True)
    parser.add_argument("--bbox-csv", type=Path, default=DEFAULT_BBOX_CSV)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples-per-source", type=int, default=50)
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
    synthetic_rows: list[dict[str, str]] = []
    synthetic_paths: list[Path] = []
    fieldnames = list(manifest_rows[0].keys())
    for row in train_next_rows:
        bbox = parse_bbox(bbox_rows[row["instance_id"]])
        source = Image.open(row["image_path"]).convert("RGB")
        for index in range(args.samples_per_source):
            synthetic_key = f"{row['instance_id']}:{args.seed}:{index}"
            instance_id = f"file_synth_next_{sha16(synthetic_key)}"
            content_id = f"asset_synth_next_{sha16('content:' + synthetic_key)}"
            image_name = f"synth_next_{row['instance_id']}_{index:03d}.png"
            image_path = images_dir / image_name
            augmented = compose_augmented(source, bbox, rng)
            augmented.save(image_path)
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
                    "review_status": "synthetic",
                    "group_key": f"synthetic_next:{row['instance_id']}",
                    "source_screen": row.get("source_screen", ""),
                    "instance_id": instance_id,
                    "content_id": content_id,
                    "original_path": row.get("original_path", row.get("image_path", "")),
                    "relative_path": str(image_path),
                    "vision_domain": "ads",
                    "asset_type": "crop",
                    "asset_role": "candidate_crop",
                    "image_scope": "crop",
                    "representation": "raw",
                    "source_root": "synthetic_next_tight_bbox",
                    "split": "train",
                    "pool_status": "trainable",
                    "pool_role": "synthetic_next_train_only",
                    "is_none_of_the_above": "0",
                    "is_confirmed_strong_hard_negative": "0",
                    "hard_negative_source": "",
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
    make_contact_sheet(synthetic_paths, args.output_dir / "synthetic_next_contact_sheet.png")
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
        "contact_sheet": str(args.output_dir / "synthetic_next_contact_sheet.png"),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
