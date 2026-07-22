from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont
from torchvision import models, transforms
from torchvision.models import MobileNet_V3_Small_Weights


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
        row["bbox_tuple"] = box
        row["source_screen"] = row.get("file", "").strip("`")
        row["geometry_score"] = row.get("score", "")
        rows.append(row)
    return rows


def infer_source_session(path: Path) -> str:
    name = path.stem
    match = re.search(r"(20\d{6}_\d{6}_[^_]+)", name)
    if match:
        return match.group(1)
    match = re.search(r"(20\d{6}_\d{6})", name)
    if match:
        return match.group(1)
    return "unknown_session"


def crop_bbox(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x, y, w, h = bbox
    left = max(0, x)
    top = max(0, y)
    right = min(image.width, x + w)
    bottom = min(image.height, y + h)
    if right <= left or bottom <= top:
        return Image.new("RGB", (1, 1), (0, 0, 0))
    return image.crop((left, top, right, bottom)).convert("RGB")


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


def build_model(checkpoint: Path, device: torch.device):
    weights = MobileNet_V3_Small_Weights.DEFAULT
    model = models.mobilenet_v3_small(weights=None)
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = torch.nn.Linear(in_features, 2)
    checkpoint_data = torch.load(checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint_data["model"])
    model.to(device)
    model.eval()
    transform = transforms.Compose(
        [
            transforms.Resize((96, 96), interpolation=transforms.InterpolationMode.BILINEAR),
            transforms.ToTensor(),
            transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std),
        ]
    )
    return model, transform


@torch.no_grad()
def score_image(model, transform, image: Image.Image, device: torch.device) -> float:
    tensor = transform(image).unsqueeze(0).to(device)
    logits = model(tensor)
    return float(torch.softmax(logits, dim=1)[0, 1].cpu())


def draw_contact_sheet(scored_rows: list[dict], output: Path, max_screens: int = 80):
    top_rows = []
    seen = set()
    for row in sorted(scored_rows, key=lambda r: (r["source_screen"], int(r["classifier_rank"]))):
        if row["source_screen"] in seen:
            continue
        seen.add(row["source_screen"])
        top_rows.append(row)
        if len(top_rows) >= max_screens:
            break
    cols = 5
    thumb = 128
    label_h = 44
    pad = 12
    rows_n = max(1, (len(top_rows) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, row in enumerate(top_rows):
        x = pad + (i % cols) * (thumb + pad)
        y = pad + (i // cols) * (thumb + label_h + pad)
        try:
            image = Image.open(row["candidate_patch"]).convert("RGB")
        except Exception:
            continue
        sheet.paste(image.resize((thumb, thumb), Image.Resampling.NEAREST), (x, y))
        draw.rectangle([x, y, x + thumb - 1, y + thumb - 1], outline=(30, 80, 200), width=2)
        draw.text((x, y + thumb + 3), f"p={float(row['p_close']):.3f} g={row['geometry_score']}", fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 17), Path(row["source_screen"]).name[:24], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-report", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--object-ratio", type=float, default=0.70)
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    patch_dir = args.output_dir / "candidate_patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device(args.device)
    model, transform = build_model(args.checkpoint, device)

    rows = parse_scan_report(args.scan_report)
    scored = []
    per_screen = defaultdict(list)
    for idx, row in enumerate(rows, start=1):
        source_screen = Path(row["source_screen"])
        if not source_screen.exists():
            continue
        image = Image.open(source_screen).convert("RGB")
        obj = canonical_object(crop_bbox(image, row["bbox_tuple"]), args.output_size, args.object_ratio)
        patch_path = patch_dir / f"candidate_{idx:06d}.png"
        obj.save(patch_path)
        p_close = score_image(model, transform, obj, device)
        x, y, w, h = row["bbox_tuple"]
        output_row = {
            "source_screen": str(source_screen.resolve()),
            "source_session": infer_source_session(source_screen),
            "bbox": f"{x},{y},{w},{h}",
            "geometry_score": row["geometry_score"],
            "p_close": f"{p_close:.6f}",
            "classifier_rank": "",
            "candidate_patch": str(patch_path.resolve()),
            "is_top1": "0",
        }
        per_screen[str(source_screen.resolve())].append(output_row)
    for candidates in per_screen.values():
        candidates.sort(key=lambda r: float(r["p_close"]), reverse=True)
        for rank, row in enumerate(candidates, start=1):
            row["classifier_rank"] = str(rank)
            row["candidate_count"] = str(len(candidates))
            row["is_top1"] = "1" if rank == 1 else "0"
            scored.append(row)
    scored.sort(key=lambda r: (r["source_screen"], int(r["classifier_rank"])))
    output_csv = args.output_dir / "ranked_candidates.csv"
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "source_screen",
            "source_session",
            "candidate_count",
            "bbox",
            "geometry_score",
            "p_close",
            "classifier_rank",
            "is_top1",
            "candidate_patch",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scored)
    draw_contact_sheet(scored, args.output_dir / "top1_contact_sheet.png")
    print(f"screens: {len(per_screen)}")
    print(f"candidates: {len(scored)}")
    print(f"ranked: {output_csv.resolve()}")
    print(f"sheet: {(args.output_dir / 'top1_contact_sheet.png').resolve()}")


if __name__ == "__main__":
    main()
