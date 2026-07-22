from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REJECT_TYPES = [
    "",
    "text_fragment",
    "decorative_x",
    "star_glint",
    "ui_crossing",
    "border_cross",
    "blob",
    "other",
]


def parse_box(text: str) -> tuple[int, int, int, int] | None:
    nums = re.findall(r"-?\d+", text)
    if len(nums) < 4:
        return None
    return tuple(map(int, nums[:4]))


def parse_scan_report(path: Path) -> list[dict]:
    rows = []
    header = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("| score |"):
            header = [part.strip() for part in line.strip("|").split("|")]
            continue
        if not header or not line.startswith("|") or line.startswith("|---"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        box = parse_box(row.get("box", ""))
        if not box:
            continue
        row["box_tuple"] = box
        row["file"] = row.get("file", "").strip("`")
        try:
            row["score_float"] = float(row.get("score", ""))
        except ValueError:
            row["score_float"] = 0.0
        rows.append(row)
    return rows


def infer_source_session(path: Path) -> str:
    name = path.stem
    match = re.search(r"(20\d{6}_\d{6}_[^_]+)", name)
    if match:
        return match.group(1)
    match = re.search(r"log__(.+?)(__\d{6}_|\Z)", name)
    if match:
        return match.group(1)[:80]
    return "unknown_session"


def resolve_source_session(path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    session = infer_source_session(path)
    if session == "unknown_session":
        print(f"warning: could not infer source_session for {path}", file=sys.stderr)
    return session


def prepare_output_dir(output_dir: Path, overwrite: bool):
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise SystemExit(f"output dir already exists and is not empty: {output_dir}\nUse --overwrite to rebuild it.")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def crop_context(image: Image.Image, box: tuple[int, int, int, int], context_scale: float, output_size: int) -> Image.Image:
    x, y, w, h = box
    cx = x + w / 2.0
    cy = y + h / 2.0
    side = max(max(w, h) * context_scale, 1.0)
    left = int(round(cx - side / 2.0))
    top = int(round(cy - side / 2.0))
    right = int(round(cx + side / 2.0))
    bottom = int(round(cy + side / 2.0))

    canvas = Image.new("RGB", (max(1, right - left), max(1, bottom - top)), (0, 0, 0))
    src_left = max(0, left)
    src_top = max(0, top)
    src_right = min(image.width, right)
    src_bottom = min(image.height, bottom)
    if src_right > src_left and src_bottom > src_top:
        crop = image.crop((src_left, src_top, src_right, src_bottom)).convert("RGB")
        canvas.paste(crop, (src_left - left, src_top - top))
    return canvas.resize((output_size, output_size), Image.Resampling.BILINEAR)


def draw_review_sheet(rows: list[dict], output: Path, max_items: int = 200):
    items = rows[:max_items]
    cols = 5
    thumb = 112
    label_h = 34
    pad = 12
    rows_n = max(1, (len(items) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, row in enumerate(items):
        path = Path(row["image_path"])
        x = pad + (i % cols) * (thumb + pad)
        y = pad + (i // cols) * (thumb + label_h + pad)
        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            continue
        sheet.paste(image.resize((thumb, thumb), Image.Resampling.NEAREST), (x, y))
        draw.rectangle([x, y, x + thumb - 1, y + thumb - 1], outline=(40, 40, 40), width=1)
        draw.text((x, y + thumb + 3), f"id={row['candidate_id']}", fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 16), f"g={row['geometry_score']}", fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def export_candidates(args):
    scan_rows = parse_scan_report(args.scan_report)
    if args.limit:
        scan_rows = scan_rows[: args.limit]
    output_dir = args.output_dir
    prepare_output_dir(output_dir, args.overwrite)
    patch_dir = output_dir / "patches"
    review_dir = output_dir / "review"
    pending_dir = review_dir / "pending"
    patch_dir.mkdir(parents=True, exist_ok=True)
    for name in ("pending", "close", "not_close", "uncertain"):
        (review_dir / name).mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    for index, row in enumerate(scan_rows, start=1):
        source_screen = Path(row["file"])
        if not source_screen.exists():
            continue
        try:
            image = Image.open(source_screen).convert("RGB")
        except Exception:
            continue
        patch = crop_context(image, row["box_tuple"], args.context_scale, args.output_size)
        candidate_id = f"cand_{index:06d}"
        patch_path = patch_dir / f"{candidate_id}.png"
        patch.save(patch_path)
        shutil.copy2(patch_path, pending_dir / patch_path.name)
        x, y, w, h = row["box_tuple"]
        manifest_rows.append(
            {
                "candidate_id": candidate_id,
                "image_path": str(patch_path.resolve()),
                "label": "",
                "review_status": "pending",
                "source_screen": str(source_screen.resolve()),
                "source_session": resolve_source_session(source_screen, args.source_session),
                "ad_source": "unknown_ad_source",
                "icon_family": "unknown_family",
                "reject_type": "",
                "candidate_score": f"{row['score_float']:.6f}",
                "geometry_score": f"{row['score_float']:.6f}",
                "bbox": f"{x},{y},{w},{h}",
                "bbox_x": x,
                "bbox_y": y,
                "bbox_w": w,
                "bbox_h": h,
                "split": "",
            }
        )

    manifest_path = output_dir / "review_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "candidate_id",
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
            "bbox_x",
            "bbox_y",
            "bbox_w",
            "bbox_h",
            "split",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    label_guide = output_dir / "label_guide.md"
    label_guide.write_text(
        "\n".join(
            [
                "# Label Guide",
                "",
                "Use folder-based review.",
                "",
                "1. Open `review/pending/` in Windows File Explorer.",
                "2. Use large icons.",
                "3. Move each image into `review/close/`, `review/not_close/`, or `review/uncertain/`.",
                "4. Run `sync_labels_from_folders.py` to update `review_manifest.csv`.",
                "",
                "Allowed labels:",
                "- `close`",
                "- `not_close`",
                "- `uncertain`",
                "",
                "`pending` means not reviewed yet.",
                "`uncertain` means a human reviewed it but cannot reliably decide.",
                "pending != uncertain.",
                "",
                "Allowed `reject_type` values for analysis only:",
                *[f"- `{value}`" for value in REJECT_TYPES if value],
                "",
                "Do not use `reject_type` as classifier label.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    draw_review_sheet(manifest_rows, output_dir / "review_sheet.png", max_items=args.sheet_items)
    print(f"candidates exported: {len(manifest_rows)}")
    print(f"manifest: {manifest_path.resolve()}")
    print(f"review sheet: {(output_dir / 'review_sheet.png').resolve()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("close_x_classifier/data/candidates"))
    parser.add_argument("--context-scale", type=float, default=3.0)
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--source-session", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sheet-items", type=int, default=200)
    args = parser.parse_args()
    export_candidates(args)


if __name__ == "__main__":
    main()
