from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


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


def as_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def review_reasons(row: dict[str, str], expected_p_threshold: float, top_p_threshold: float) -> list[str]:
    reasons: list[str] = []
    expected_family = row.get("expected_family", "")
    expected_p = as_float(row.get("expected_p", ""), 999.0)
    top_family = row.get("top_family", "")
    top_p = as_float(row.get("top_p", ""), 0.0)
    if expected_family and expected_p < expected_p_threshold:
        reasons.append("expected_low_confidence")
    if expected_family and top_family and top_family != expected_family:
        reasons.append("expected_top_disagreement")
    if top_p < top_p_threshold:
        reasons.append("low_top_score")
    return reasons


def contact_sheet(rows: list[dict[str, Any]], output: Path, title: str) -> None:
    cols, thumb, label_h, pad = 6, 126, 66, 8
    rows_n = max(1, math.ceil(len(rows) / cols))
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((pad, 2), title[:160], fill=(20, 20, 20), font=font)
    for pos, row in enumerate(rows):
        x = pad + (pos % cols) * (thumb + pad)
        y = pad + (pos // cols) * (thumb + label_h + pad) + pad
        try:
            image = Image.open(row["bbox_crop"]).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        except Exception:
            image = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(image, (x, y))
        expected = row.get("expected_family") or "-"
        expected_p = as_float(row.get("expected_p", ""))
        top = row.get("top_family") or "-"
        top_p = as_float(row.get("top_p", ""))
        draw.text((x, y + thumb + 2), f"top={top} {top_p:.2f} exp={expected} {expected_p:.2f}", fill=(130, 20, 20), font=font)
        draw.text((x, y + thumb + 18), str(row.get("template_name", ""))[:28], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 34), str(row.get("review_reasons", ""))[:34], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 50), str(row.get("event_id", ""))[:34], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a small manual review set from click-success scan predictions.")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-p-threshold", type=float, default=0.5)
    parser.add_argument("--top-p-threshold", type=float, default=0.75)
    args = parser.parse_args()

    rows = read_csv(args.predictions)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        reasons = review_reasons(row, args.expected_p_threshold, args.top_p_threshold)
        if not reasons:
            continue
        event_id = row.get("event_id", "")
        if event_id in seen:
            continue
        seen.add(event_id)
        selected.append({**row, "review_reasons": "|".join(reasons)})
    selected.sort(
        key=lambda row: (
            "expected_low_confidence" not in row["review_reasons"],
            "expected_top_disagreement" not in row["review_reasons"],
            as_float(row.get("expected_p", ""), 999.0),
            as_float(row.get("top_p", ""), 999.0),
            row.get("event_id", ""),
        )
    )

    fields = [
        "event_id",
        "review_reasons",
        "proposal_source",
        "template_name",
        "expected_family",
        "expected_p",
        "top_family",
        "top_p",
        "p_x_mark",
        "p_arrow",
        "p_free",
        "p_got",
        "bbox",
        "click_xy",
        "pre_click",
        "bbox_crop",
        "bbox_context_crop",
        "event_dir",
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "review_needed.csv", selected, fields)
    (args.output_dir / "review_event_ids.txt").write_text(
        "\n".join(row["event_id"] for row in selected) + ("\n" if selected else ""),
        encoding="utf-8",
    )
    contact_sheet(selected, args.output_dir / "review_needed_contact_sheet.png", "Click-success events that need review")

    summary = {
        "predictions": str(args.predictions),
        "selected_events": len(selected),
        "expected_p_threshold": args.expected_p_threshold,
        "top_p_threshold": args.top_p_threshold,
        "reason_counts": {},
        "output_dir": str(args.output_dir),
    }
    for row in selected:
        for reason in row["review_reasons"].split("|"):
            summary["reason_counts"][reason] = summary["reason_counts"].get(reason, 0) + 1
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
