from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont


def load_trainer_module(path: Path):
    spec = importlib.util.spec_from_file_location("vftrain", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import trainer from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["vftrain"] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def contact_sheet(rows: list[dict[str, object]], family: str, output: Path, max_items: int = 120) -> None:
    items = rows[:max_items]
    cols, thumb, label_h, pad = 8, 104, 58, 8
    rows_n = max(1, math.ceil(len(items) / cols))
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, row in enumerate(items):
        x = pad + (index % cols) * (thumb + pad)
        y = pad + (index // cols) * (thumb + label_h + pad)
        try:
            image = Image.open(str(row["image_path"])).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        except Exception:
            image = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(image, (x, y))
        draw.text((x, y + thumb + 2), f"{family}={float(row[f'p_{family}']):.2f} true={str(row['families'])[:14]}", fill=(130, 20, 20), font=font)
        draw.text((x, y + thumb + 18), f"arrow={float(row.get('p_arrow') or 0):.2f} got={float(row.get('p_got') or 0):.2f}", fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 34), str(row.get("instance_id", ""))[:24], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine false positives for one family from an assigned split.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--trainer", type=Path, default=Path("vision_platform/ads/tools/train_visual_family_smoke.py"))
    parser.add_argument("--family", required=True)
    parser.add_argument("--split", default="train", choices=["train", "val", "test"])
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    trainer = load_trainer_module(args.trainer)
    if args.family not in trainer.FAMILIES:
        raise SystemExit(f"unknown family: {args.family}")
    device = torch.device(args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    rows = trainer.read_manifest(args.run_dir / "assigned_manifest.csv")
    split_rows = [row for row in rows if row.split == args.split]
    model = trainer.build_model(device)
    checkpoint = torch.load(args.run_dir / "best.pt", map_location=device)
    model.load_state_dict(checkpoint["model"])
    y_true, y_prob = trainer.evaluate(model, split_rows, device, 32, args.threshold)
    family_index = trainer.FAMILIES.index(args.family)

    false_positives: list[dict[str, object]] = []
    for index, row in enumerate(split_rows):
        if y_true[index, family_index] == 0 and y_prob[index, family_index] >= args.threshold:
            output_row: dict[str, object] = {
                f"p_{args.family}": float(y_prob[index, family_index]),
                "families": row.families,
                "instance_id": row.instance_id,
                "content_id": row.content_id,
                "image_path": str(row.image_path),
                "relative_path": row.relative_path,
            }
            for family in trainer.FAMILIES:
                output_row[f"p_{family}"] = float(y_prob[index, trainer.FAMILIES.index(family)])
            false_positives.append(output_row)
    false_positives.sort(key=lambda row: float(row[f"p_{args.family}"]), reverse=True)
    content_ids = sorted({str(row["content_id"]) for row in false_positives if row.get("content_id")})

    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        f"p_{args.family}",
        "families",
        "instance_id",
        "content_id",
        "image_path",
        "relative_path",
        *[f"p_{family}" for family in trainer.FAMILIES if family != args.family],
    ]
    write_csv(args.output_dir / f"{args.family}_{args.split}_false_positives.csv", false_positives, fields)
    (args.output_dir / f"{args.family}_{args.split}_hard_negative_content_ids.txt").write_text(
        "\n".join(content_ids) + ("\n" if content_ids else ""),
        encoding="utf-8",
    )
    contact_sheet(false_positives, args.family, args.output_dir / f"{args.family}_{args.split}_false_positives.png")
    summary = {
        "run_dir": str(args.run_dir),
        "family": args.family,
        "split": args.split,
        "threshold": args.threshold,
        "split_rows": len(split_rows),
        "false_positive_rows": len(false_positives),
        "false_positive_content_ids": len(content_ids),
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
