from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


FAMILIES = ["x_mark", "play_triangle", "google_play", "next", "free", "got", "arrow"]


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


def contact_sheet(rows: list[dict[str, str]], family: str, threshold: float, output: Path, max_items: int = 120) -> None:
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
            image = Image.open(row["image_path"]).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        except Exception:
            image = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(image, (x, y))
        score = float(row.get(f"p_{family}") or 0.0)
        draw.text((x, y + thumb + 2), f"{family}={score:.2f} true={row.get('families','')[:14]}", fill=(130, 20, 20), font=font)
        draw.text((x, y + thumb + 18), f"arrow={float(row.get('p_arrow') or 0):.2f} got={float(row.get('p_got') or 0):.2f}", fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 34), str(row.get("instance_id", ""))[:24], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export false-positive contact sheets for a visual family.")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--threshold", type=float, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    thresholds = args.threshold or [0.5]
    rows = read_csv(args.predictions)
    fields = [
        f"p_{args.family}",
        "families",
        "instance_id",
        "content_id",
        "relative_path",
        "image_path",
        *[f"p_{family}" for family in FAMILIES if family != args.family],
    ]
    summary = {}
    for threshold in thresholds:
        false_positives = [
            row
            for row in rows
            if int(float(row.get(f"true_{args.family}") or 0)) == 0 and float(row.get(f"p_{args.family}") or 0.0) >= threshold
        ]
        false_positives.sort(key=lambda row: float(row.get(f"p_{args.family}") or 0.0), reverse=True)
        suffix = str(threshold).replace(".", "_")
        write_csv(args.output_dir / f"{args.family}_false_positives_threshold_{suffix}.csv", false_positives, fields)
        contact_sheet(false_positives, args.family, threshold, args.output_dir / f"{args.family}_false_positives_threshold_{suffix}.png")
        summary[str(threshold)] = len(false_positives)
        print(f"{args.family} threshold={threshold} false_positives={len(false_positives)}")
    (args.output_dir / "summary.txt").write_text("\n".join(f"{key}: {value}" for key, value in summary.items()), encoding="utf-8")
    print(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
