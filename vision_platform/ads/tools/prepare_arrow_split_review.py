from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ARROW_SPLIT_OPTIONS = [
    "play_triangle",
    "double_triangle",
    "single_chevron",
    "double_chevron",
    "double_chevron_text",
    "back_arrow",
    "next_button",
    "arrow_other",
    "x_mark",
    "negative",
    "other",
    "uncertain",
]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def reason_for(row: sqlite3.Row) -> str:
    families = str(row["families"] or "")
    rel = str(row["relative_path"] or "").lower()
    reasons: list[str] = []
    if "arrow" in families:
        reasons.append("current_arrow")
    if families == "next":
        reasons.append("current_next")
    if "close_11" in rel or "close_15" in rel:
        reasons.append("known_double_chevron_template")
    return "|".join(reasons) or "candidate"


def read_candidates(con: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT
            v.instance_id,
            v.families,
            v.review_status AS visual_review_status,
            a.content_id,
            a.original_path,
            a.relative_path,
            a.filename,
            a.source_root,
            a.image_scope,
            a.vision_domain,
            COALESCE(r.representation, 'unknown') AS representation
        FROM visual_family_reviews v
        JOIN assets a ON a.instance_id = v.instance_id
        LEFT JOIN image_reviews r ON r.instance_id = v.instance_id
        WHERE v.review_status = 'reviewed'
          AND a.vision_domain IN ('ads', 'shared')
          AND a.image_scope = 'crop'
          AND COALESCE(r.representation, 'unknown') NOT IN ('edge_glyph', 'binary_mask', 'debug_overlay', 'annotated', 'grayscale')
          AND (
              v.families LIKE '%arrow%'
              OR v.families = 'next'
              OR a.relative_path LIKE '%close_11%'
              OR a.relative_path LIKE '%close_15%'
          )
        ORDER BY
          CASE WHEN v.families LIKE '%arrow%' THEN 0 ELSE 1 END,
          a.relative_path COLLATE NOCASE
        """,
    ).fetchall()
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row["instance_id"] in seen:
            continue
        seen.add(row["instance_id"])
        output.append(
            {
                "instance_id": row["instance_id"],
                "content_id": row["content_id"],
                "current_families": row["families"],
                "review_reason": reason_for(row),
                "relative_path": row["relative_path"],
                "original_path": row["original_path"],
                "filename": row["filename"],
                "source_root": row["source_root"],
                "vision_domain": row["vision_domain"],
                "representation": row["representation"],
            }
        )
        if limit > 0 and len(output) >= limit:
            break
    return output


def draw_contact_sheet(rows: list[dict[str, Any]], output: Path, max_items: int = 180) -> None:
    items = rows[:max_items]
    cols, thumb, label_h, pad = 8, 96, 54, 8
    rows_n = max(1, (len(items) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, row in enumerate(items):
        x = pad + (index % cols) * (thumb + pad)
        y = pad + (index // cols) * (thumb + label_h + pad)
        try:
            image = Image.open(row["original_path"]).convert("RGB")
            image.thumbnail((thumb, thumb), Image.Resampling.NEAREST)
            canvas = Image.new("RGB", (thumb, thumb), (20, 20, 20))
            canvas.paste(image, ((thumb - image.width) // 2, (thumb - image.height) // 2))
        except Exception:
            canvas = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(canvas, (x, y))
        draw.text((x, y + thumb + 2), f"{index + 1:03d} {row['current_families']}"[:22], fill=(130, 20, 20), font=font)
        draw.text((x, y + thumb + 18), str(row["review_reason"])[:24], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 34), str(row["filename"])[:24], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an Ads arrow-family split review batch.")
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/arrow_split_review"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    con = open_db(args.db)
    rows = read_candidates(con, args.limit)
    con.close()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "instance_id",
        "content_id",
        "current_families",
        "review_reason",
        "relative_path",
        "original_path",
        "filename",
        "source_root",
        "vision_domain",
        "representation",
    ]
    instances_csv = args.output_dir / "arrow_split_instances.csv"
    write_csv(instances_csv, rows, fields)
    draw_contact_sheet(rows, args.output_dir / "arrow_split_contact_sheet.png")

    config = {
        "instance_list_csv": str(instances_csv),
        "instance_list_column": "instance_id",
        "family_options": ARROW_SPLIT_OPTIONS,
        "default_filter": {
            "status": "all",
            "family": "all",
            "source": "all",
            "path_contains": "",
            "search": "",
            "sort": "review_list",
            "selection_mode": "single",
            "default_pick": "previous saved",
        },
        "arrow_split_options": ARROW_SPLIT_OPTIONS,
        "note": "Review current arrow/next-like crops into arrow subfamilies. Training currently maps arrow_* labels back to the parent arrow head.",
    }
    config_path = args.output_dir / "ads_family_review_gui_arrow_split_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    guide = [
        "# Arrow Split Review Guide",
        "",
        "Goal: split the broad parent `arrow` label into visual subfamilies. The current training builder maps `arrow_*` labels back to the parent `arrow` head until we explicitly change the model taxonomy.",
        "",
        "Use one label per image unless the crop truly contains two independent visual targets.",
        "",
        "- `play_triangle`: a single play triangle, e.g. `▶`.",
        "- `double_triangle`: two play triangles or skip mark, e.g. `▶▶`, `▶▶|`.",
        "- `single_chevron`: a single chevron, e.g. `>` or `<`, without a play-triangle fill.",
        "- `double_chevron`: two or more chevrons, e.g. `>>`, without readable text as the main crop.",
        "- `double_chevron_text`: `>>` plus readable text, especially `>> Ad`.",
        "- `back_arrow`: a normal back/left arrow, often boxed, e.g. `←`.",
        "- `next_button`: readable `Next` pill/button. Use this only when the word `Next` is a first-class visual cue.",
        "- `x_mark`: this crop is actually an X/close mark, not arrow.",
        "- `negative`: clearly not an actionable visual family.",
        "- `other`: valid-looking visual pattern, but not one of the above.",
        "- `uncertain`: genuinely hard to decide.",
        "",
        "Practical rule: `▶▶|` goes to `double_triangle`; `>> Ad` goes to `double_chevron_text`; readable `Next` goes to `next_button`.",
    ]
    (args.output_dir / "label_guide.md").write_text("\n".join(guide), encoding="utf-8")
    summary = {
        "rows": len(rows),
        "current_family_counts": {},
        "reason_counts": {},
        "instances_csv": str(instances_csv),
        "contact_sheet": str(args.output_dir / "arrow_split_contact_sheet.png"),
        "label_guide": str(args.output_dir / "label_guide.md"),
        "config": str(config_path),
    }
    for row in rows:
        summary["current_family_counts"][row["current_families"]] = summary["current_family_counts"].get(row["current_families"], 0) + 1
        for reason in row["review_reason"].split("|"):
            summary["reason_counts"][reason] = summary["reason_counts"].get(reason, 0) + 1
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
