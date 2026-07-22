from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import zipfile
from collections import Counter
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


def copy_if_exists(source: Path, dest: Path) -> None:
    if source.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


def annotation_map(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    by_screen: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_screen.setdefault(row["screen_id"], []).append(row)
    return by_screen


def bbox_tuple(row: dict[str, str]) -> tuple[float, float, float, float]:
    return (
        float(row["bbox_x"]),
        float(row["bbox_y"]),
        float(row["bbox_w"]),
        float(row["bbox_h"]),
    )


def draw_sheet(
    screens: list[dict[str, str]],
    boxes_by_screen: dict[str, list[dict[str, str]]],
    output: Path,
    *,
    title: str,
    max_items: int = 80,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    items = screens[:max_items]
    cols, thumb_w, thumb_h, label_h, pad = 4, 240, 135, 46, 8
    rows_n = max(1, math.ceil(len(items) / cols))
    sheet = Image.new("RGB", (cols * (thumb_w + pad) + pad, rows_n * (thumb_h + label_h + pad) + pad + 18), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((pad, 4), title[:180], fill=(20, 20, 20), font=font)
    for index, screen in enumerate(items):
        x = pad + (index % cols) * (thumb_w + pad)
        y = pad + 18 + (index // cols) * (thumb_h + label_h + pad)
        image_path = Path(screen["image_path"])
        try:
            image = Image.open(image_path).convert("RGB")
        except Exception:
            image = Image.new("RGB", (thumb_w, thumb_h), (80, 80, 80))
        sx = thumb_w / max(image.width, 1)
        sy = thumb_h / max(image.height, 1)
        image = image.resize((thumb_w, thumb_h), Image.Resampling.BILINEAR)
        item_draw = ImageDraw.Draw(image)
        for box in boxes_by_screen.get(screen["screen_id"], []):
            bx, by, bw, bh = bbox_tuple(box)
            item_draw.rectangle((bx * sx, by * sy, (bx + bw) * sx, (by + bh) * sy), outline=(0, 230, 0), width=2)
            item_draw.text((bx * sx, max(0, by * sy - 10)), box.get("label", ""), fill=(0, 180, 0), font=font)
        sheet.paste(image, (x, y))
        line1 = f"{screen.get('screen_id', '')} {screen.get('screen_state', screen.get('dataset_role', ''))}"[:34]
        line2 = f"{screen.get('proposal_source', '')} {screen.get('template_name', '')}"[:34]
        line3 = f"boxes={screen.get('positive_bbox_count', '')} split={screen.get('split', '')}"[:34]
        draw.text((x, y + thumb_h + 2), line1, fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb_h + 17), line2, fill=(80, 80, 80), font=font)
        draw.text((x, y + thumb_h + 32), line3, fill=(80, 80, 80), font=font)
    sheet.save(output)


def build_manifest(
    manual_screens: list[dict[str, str]],
    manual_annotations: list[dict[str, str]],
    weak_screens: list[dict[str, str]],
    weak_annotations: list[dict[str, str]],
) -> list[dict[str, Any]]:
    manual_by_screen = annotation_map(manual_annotations)
    weak_by_screen = annotation_map(weak_annotations)
    rows: list[dict[str, Any]] = []
    for dataset_name, screens, by_screen in [
        ("manual_review", manual_screens, manual_by_screen),
        ("click_success_weak_positive", weak_screens, weak_by_screen),
    ]:
        for screen in screens:
            boxes = by_screen.get(screen["screen_id"], [])
            if boxes:
                for box in boxes:
                    rows.append(
                        {
                            "dataset_source": dataset_name,
                            "screen_id": screen["screen_id"],
                            "image_path": screen["image_path"],
                            "original_path": screen.get("original_path", ""),
                            "event_json": screen.get("event_json", ""),
                            "instance_id": screen.get("instance_id", ""),
                            "content_id": screen.get("content_id", ""),
                            "source_session": screen.get("source_session", ""),
                            "screen_state": screen.get("screen_state", ""),
                            "dataset_role": screen.get("dataset_role", "manual_positive"),
                            "proposal_source": box.get("proposal_source", screen.get("proposal_source", "")),
                            "template_name": box.get("template_name", screen.get("template_name", "")),
                            "screen_change_score": box.get("screen_change_score", screen.get("screen_change_score", "")),
                            "bbox_x": box.get("bbox_x", ""),
                            "bbox_y": box.get("bbox_y", ""),
                            "bbox_w": box.get("bbox_w", ""),
                            "bbox_h": box.get("bbox_h", ""),
                            "category": box.get("category", "action_candidate"),
                            "label": box.get("label", ""),
                            "split_group": screen.get("split_group", box.get("split_group", "")),
                            "split": screen.get("split", box.get("split", "")),
                        }
                    )
            else:
                rows.append(
                    {
                        "dataset_source": dataset_name,
                        "screen_id": screen["screen_id"],
                        "image_path": screen["image_path"],
                        "original_path": screen.get("original_path", ""),
                        "event_json": screen.get("event_json", ""),
                        "instance_id": screen.get("instance_id", ""),
                        "content_id": screen.get("content_id", ""),
                        "source_session": screen.get("source_session", ""),
                        "screen_state": screen.get("screen_state", ""),
                        "dataset_role": "negative_screen",
                        "proposal_source": screen.get("proposal_source", ""),
                        "template_name": screen.get("template_name", ""),
                        "screen_change_score": screen.get("screen_change_score", ""),
                        "bbox_x": "",
                        "bbox_y": "",
                        "bbox_w": "",
                        "bbox_h": "",
                        "category": "none",
                        "label": "negative_screen",
                        "split_group": screen.get("split_group", ""),
                        "split": screen.get("split", ""),
                    }
                )
    return rows


def bbox_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    widths = [float(row["bbox_w"]) for row in rows if row.get("bbox_w")]
    heights = [float(row["bbox_h"]) for row in rows if row.get("bbox_h")]
    areas = [w * h for w, h in zip(widths, heights)]

    def stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"count": 0, "min": 0, "mean": 0, "max": 0}
        return {
            "count": len(values),
            "min": round(min(values), 3),
            "mean": round(sum(values) / len(values), 3),
            "max": round(max(values), 3),
        }

    return {
        "width": stats(widths),
        "height": stats(heights),
        "area": stats(areas),
    }


def zip_dir(source_dir: Path, output_zip: Path) -> None:
    if output_zip.exists():
        output_zip.unlink()
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file() and path != output_zip:
                archive.write(path, path.relative_to(source_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Package detector dataset evidence for external review.")
    parser.add_argument("--manual-dataset", type=Path, default=Path("vision_platform/ads/datasets/detector/action_candidate_20260719"))
    parser.add_argument("--weak-dataset", type=Path, default=Path("vision_platform/ads/datasets/detector/click_success_weak_20260719"))
    parser.add_argument("--smoke-run", type=Path, default=Path("vision_platform/ads/pilot/detector_smoke/action_candidate_20260719_seed42_max120"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/temp/detector_evidence_for_sol_20260719"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {args.output_dir}")
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manual_screens = read_csv(args.manual_dataset / "screens.csv")
    manual_annotations = read_csv(args.manual_dataset / "annotations.csv")
    weak_screens = read_csv(args.weak_dataset / "screens.csv")
    weak_annotations = read_csv(args.weak_dataset / "annotations.csv")
    manual_by_screen = annotation_map(manual_annotations)
    weak_by_screen = annotation_map(weak_annotations)
    manifest_rows = build_manifest(manual_screens, manual_annotations, weak_screens, weak_annotations)
    fields = [
        "dataset_source",
        "screen_id",
        "image_path",
        "original_path",
        "event_json",
        "instance_id",
        "content_id",
        "source_session",
        "screen_state",
        "dataset_role",
        "proposal_source",
        "template_name",
        "screen_change_score",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "category",
        "label",
        "split_group",
        "split",
    ]
    write_csv(args.output_dir / "detector_dataset_manifest.csv", manifest_rows, fields)
    write_csv(args.output_dir / "manual_screens.csv", manual_screens, list(manual_screens[0].keys()))
    write_csv(args.output_dir / "manual_annotations.csv", manual_annotations, list(manual_annotations[0].keys()))
    write_csv(args.output_dir / "click_success_weak_screens.csv", weak_screens, list(weak_screens[0].keys()))
    write_csv(args.output_dir / "click_success_weak_annotations.csv", weak_annotations, list(weak_annotations[0].keys()))

    reports = args.output_dir / "reports"
    copy_if_exists(args.manual_dataset / "summary.json", reports / "manual_dataset_summary.json")
    copy_if_exists(args.weak_dataset / "summary.json", reports / "click_success_weak_summary.json")
    copy_if_exists(args.smoke_run / "summary.json", reports / "smoke_run_summary.json")
    copy_if_exists(args.smoke_run / "eval_predictions.csv", reports / "smoke_eval_predictions.csv")
    copy_if_exists(args.smoke_run / "eval_overlay_sheet.png", reports / "smoke_eval_overlay_sheet.png")

    sheets = args.output_dir / "contact_sheets"
    manual_positive = [screen for screen in manual_screens if int(float(screen.get("positive_bbox_count") or 0)) > 0]
    negative = [screen for screen in manual_screens if int(float(screen.get("positive_bbox_count") or 0)) == 0]
    val_test = [screen for screen in manual_screens if screen.get("split") in {"val", "test"}]
    draw_sheet(manual_positive, manual_by_screen, sheets / "manual_positive_bbox_overlay.png", title="Manual reviewed positive bbox")
    draw_sheet(weak_screens, weak_by_screen, sheets / "click_success_weak_positive_bbox_overlay.png", title="Click-success weak positive bbox")
    draw_sheet(negative, manual_by_screen, sheets / "negative_screen_contact_sheet.png", title="Negative screen: no bbox")
    if val_test:
        draw_sheet(val_test, manual_by_screen, sheets / "val_test_bbox_overlay.png", title="Val/test bbox overlay")

    summary = {
        "manual_dataset": str(args.manual_dataset),
        "weak_dataset": str(args.weak_dataset),
        "smoke_run": str(args.smoke_run),
        "manual_screens": len(manual_screens),
        "manual_annotations": len(manual_annotations),
        "manual_negative_screens": len(negative),
        "weak_screens": len(weak_screens),
        "weak_annotations": len(weak_annotations),
        "manifest_rows": len(manifest_rows),
        "dataset_source_counts": dict(Counter(row["dataset_source"] for row in manifest_rows)),
        "label_counts": dict(Counter(row["label"] for row in manifest_rows)),
        "proposal_source_counts": dict(Counter(row["proposal_source"] for row in manifest_rows if row.get("proposal_source"))),
        "bbox_stats": bbox_stats(manifest_rows),
        "outputs": {
            "manifest": str(args.output_dir / "detector_dataset_manifest.csv"),
            "contact_sheets": str(sheets),
            "reports": str(reports),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Detector Evidence Package",
        "",
        f"- Manual screens: {len(manual_screens)}",
        f"- Manual annotations: {len(manual_annotations)}",
        f"- Manual negative screens: {len(negative)}",
        f"- Click-success weak screens: {len(weak_screens)}",
        f"- Click-success weak annotations: {len(weak_annotations)}",
        "",
        "## Proposal Sources",
    ]
    for source, count in sorted(summary["proposal_source_counts"].items()):
        lines.append(f"- `{source}`: {count}")
    lines += [
        "",
        "## Files",
        "",
        "- `detector_dataset_manifest.csv`",
        "- `contact_sheets/manual_positive_bbox_overlay.png`",
        "- `contact_sheets/click_success_weak_positive_bbox_overlay.png`",
        "- `contact_sheets/negative_screen_contact_sheet.png`",
        "- `reports/manual_dataset_summary.json`",
        "- `reports/click_success_weak_summary.json`",
        "- `reports/smoke_run_summary.json`",
    ]
    (args.output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    zip_path = args.output_dir.with_suffix(".zip")
    zip_dir(args.output_dir, zip_path)
    print(json.dumps({**summary, "zip": str(zip_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
