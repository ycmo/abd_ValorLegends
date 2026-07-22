from __future__ import annotations

import argparse
import csv
import re
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}
SHORT_REVIEW_DIR = Path("close_x_classifier/review")


def parse_bbox(text: str) -> tuple[int, int, int, int] | None:
    nums = re.findall(r"-?\d+", text or "")
    if len(nums) < 4:
        return None
    return tuple(map(int, nums[:4]))


def infer_source_session(name: str) -> str:
    match = re.search(r"(20\d{6}_\d{6}_[^_]+)", name)
    if match:
        return match.group(1)
    match = re.search(r"(20\d{6}_\d{6})", name)
    if match:
        return match.group(1)
    return "unknown_session"


def read_manifest(path: Path) -> dict[str, dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return {row["candidate_id"]: row for row in csv.DictReader(f)}


def canonical_object(image: Image.Image, output_size: int, object_ratio: float) -> Image.Image:
    image = image.convert("RGB")
    target_max = max(1, round(output_size * object_ratio))
    scale = target_max / max(image.width, image.height)
    new_w = max(1, round(image.width * scale))
    new_h = max(1, round(image.height * scale))
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (output_size, output_size), (0, 0, 0))
    canvas.paste(resized, ((output_size - new_w) // 2, (output_size - new_h) // 2))
    return canvas


def crop_bbox(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x, y, w, h = bbox
    left = max(0, x)
    top = max(0, y)
    right = min(image.width, x + w)
    bottom = min(image.height, y + h)
    if right <= left or bottom <= top:
        return Image.new("RGB", (1, 1), (0, 0, 0))
    return image.crop((left, top, right, bottom)).convert("RGB")


def candidate_from_manifest(path: Path, manifest: dict[str, dict], source_lookup: dict[str, Path]) -> tuple[Image.Image, dict] | None:
    row = manifest.get(path.stem)
    if not row:
        return None
    bbox = parse_bbox(row.get("bbox", ""))
    source_screen = Path(row["source_screen"])
    if not source_screen.exists():
        source_screen = source_lookup.get(source_screen.name, source_screen)
    if not bbox or not source_screen.exists():
        return None
    image = Image.open(source_screen).convert("RGB")
    return crop_bbox(image, bbox), row


def image_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def unique_image_files(paths: list[Path]) -> list[Path]:
    files = []
    seen = set()
    for directory in paths:
        for path in image_files(directory):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
    return sorted(files)


def draw_sheet(rows: list[dict], output: Path, max_items: int = 240):
    items = rows[:max_items]
    cols = 8
    thumb = 96
    label_h = 28
    pad = 8
    rows_n = max(1, (len(items) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, row in enumerate(items):
        x = pad + (i % cols) * (thumb + pad)
        y = pad + (i // cols) * (thumb + label_h + pad)
        try:
            image = Image.open(row["image_path"]).convert("RGB")
        except Exception:
            continue
        sheet.paste(image, (x, y))
        color = (40, 140, 60) if row["label"] == "close" else (190, 50, 50)
        draw.rectangle([x, y, x + thumb - 1, y + thumb - 1], outline=color, width=2)
        draw.text((x, y + thumb + 3), row["label"], fill=color, font=font)
        draw.text((x, y + thumb + 15), Path(row["original_name"]).stem[:14], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def write_manifest(rows: list[dict], output: Path):
    fieldnames = [
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
        "source_type",
        "original_name",
        "split",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build(args):
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir already exists and is not empty: {args.output_dir}\nUse --overwrite to rebuild it.")
        shutil.rmtree(args.output_dir)
    image_dir = args.output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(args.review_manifest)
    source_lookup = {}
    close_dirs = [args.close_dir, SHORT_REVIEW_DIR / "close"]
    not_close_dirs = [args.not_close_dir, SHORT_REVIEW_DIR / "not_close"]
    for directory in close_dirs + not_close_dirs:
        for path in image_files(directory):
            source_lookup[path.name] = path

    rows = []
    index = 0
    for label, paths in (("close", close_dirs), ("not_close", not_close_dirs)):
        for path in unique_image_files(paths):
            if label == "not_close" and path.stem not in manifest:
                continue
            if label == "close":
                candidate = candidate_from_manifest(path, manifest, source_lookup)
                if candidate:
                    raw_image, meta = candidate
                    source_type = "manifest_bbox_positive"
                else:
                    raw_image = Image.open(path).convert("RGB")
                    meta = {}
                    source_type = "legacy_tight_positive"
            else:
                candidate = candidate_from_manifest(path, manifest, source_lookup)
                if not candidate:
                    continue
                raw_image, meta = candidate
                source_type = "manifest_bbox_negative"

            index += 1
            output_path = image_dir / f"stage0_6_{index:05d}_{label}.png"
            canonical_object(raw_image, args.output_size, args.object_ratio).save(output_path)
            source_session = meta.get("source_session") or infer_source_session(path.stem)
            rows.append(
                {
                    "image_path": str(output_path.resolve()),
                    "label": label,
                    "review_status": "reviewed",
                    "source_screen": meta.get("source_screen") or str(path.resolve()),
                    "source_session": source_session,
                    "ad_source": meta.get("ad_source", "unknown_ad_source"),
                    "icon_family": meta.get("icon_family") or (path.stem if label == "close" else "negative_unknown_family"),
                    "reject_type": meta.get("reject_type", ""),
                    "candidate_score": meta.get("candidate_score", ""),
                    "geometry_score": meta.get("geometry_score", meta.get("candidate_score", "")),
                    "bbox": meta.get("bbox", ""),
                    "source_type": source_type,
                    "original_name": path.name,
                    "split": "",
                }
            )

    manifest_path = args.output_dir / "manifest.csv"
    write_manifest(rows, manifest_path)
    draw_sheet(rows, args.output_dir / "contact_sheet.png")
    counts = Counter(row["label"] for row in rows)
    source_types = Counter(row["source_type"] for row in rows)
    print(f"wrote: {manifest_path.resolve()}")
    print(f"counts: {dict(counts)}")
    print(f"source_type counts: {dict(source_types)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-manifest", type=Path, default=Path("close_x_classifier/data/review_batch_001/review_manifest.csv"))
    parser.add_argument("--close-dir", type=Path, default=Path("close_x_classifier/data/review_batch_001/review/close"))
    parser.add_argument("--not-close-dir", type=Path, default=Path("close_x_classifier/data/review_batch_001/review/not_close"))
    parser.add_argument("--output-dir", type=Path, default=Path("close_x_classifier/data/stage0_6_canonical_object_poc"))
    parser.add_argument("--object-ratio", type=float, default=0.70)
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
