from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


FAMILIES = [
    "x_mark",
    "play_triangle",
    "google_play",
    "next",
    "free",
    "got",
    "arrow",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def prediction_paths(input_dir: Path) -> list[Path]:
    paths = sorted(input_dir.glob("run_seed*/test_predictions.csv"))
    if paths:
        return paths
    direct = input_dir / "test_predictions.csv"
    return [direct] if direct.exists() else []


def seed_name(path: Path) -> str:
    if path.parent.name.startswith("run_seed"):
        return path.parent.name.replace("run_seed", "seed")
    return path.parent.name


def load_current_visual_reviews(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT instance_id, families FROM visual_family_reviews").fetchall()
        return {row["instance_id"]: row["families"] or "" for row in rows}
    finally:
        conn.close()


def write_id_file(path: Path, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")


def write_gui_config(path: Path, ids_file: Path) -> None:
    config = {
        "default_filter": {
            "domain": "ads_shared",
            "role": "all",
            "scope": "crop",
            "source": "all",
            "status": "all",
            "visual_status": "all",
            "search": "",
            "sort": "image_signature",
            "include_instance_ids_file": str(ids_file),
        },
        "sort_mode": "image_signature",
    }
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def is_none_of_the_above(raw: dict[str, str]) -> bool:
    return all(int(float(raw.get(f"true_{family}") or 0)) == 0 for family in FAMILIES)


def build_rows(prediction_files: list[Path], threshold: float, current_families: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pred_path in prediction_files:
        seed = seed_name(pred_path)
        for raw in read_csv(pred_path):
            if not is_none_of_the_above(raw):
                continue
            scores = {family: float(raw.get(f"p_{family}") or 0.0) for family in FAMILIES}
            triggered = {family: score for family, score in scores.items() if score >= threshold}
            if not triggered:
                continue
            top_family, top_score = max(scores.items(), key=lambda item: item[1])
            instance_id = raw.get("instance_id", "")
            rows.append(
                {
                    "seed": seed,
                    "instance_id": instance_id,
                    "content_id": raw.get("content_id", ""),
                    "relative_path": raw.get("relative_path", ""),
                    "dataset_image_path": raw.get("image_path", ""),
                    "families": raw.get("families", ""),
                    "current_db_families": current_families.get(instance_id, ""),
                    "top_family": top_family,
                    "top_score": f"{top_score:.5f}",
                    "triggered_families": "|".join(f"{family}:{score:.5f}" for family, score in sorted(triggered.items())),
                    **{f"p_{family}": f"{scores[family]:.5f}" for family in FAMILIES},
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare all-zero none-of-the-above false activations for GUI review.")
    parser.add_argument("--predictions-dir", default="vision_platform/ads/pilot/visual_family_smoke")
    parser.add_argument("--db", default="vision_platform/vision_assets/review/vision_review.db")
    parser.add_argument("--output-dir", default="vision_platform/ads/pilot/visual_family_smoke/none_of_the_above_review")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    predictions_dir = Path(args.predictions_dir)
    output_dir = Path(args.output_dir)
    prediction_files = prediction_paths(predictions_dir)
    if not prediction_files:
        raise SystemExit(f"No test_predictions.csv files found under {predictions_dir}")

    rows = build_rows(prediction_files, args.threshold, load_current_visual_reviews(Path(args.db)))
    output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "seed",
        "instance_id",
        "content_id",
        "relative_path",
        "dataset_image_path",
        "families",
        "current_db_families",
        "top_family",
        "top_score",
        "triggered_families",
        *[f"p_{family}" for family in FAMILIES],
    ]
    write_csv(output_dir / "none_of_the_above_false_activations.csv", rows, fieldnames)

    ids = sorted({row["instance_id"] for row in rows})
    ids_file = output_dir / "none_of_the_above_false_activation_instance_ids.txt"
    config_file = output_dir / "review_gui_none_of_the_above_false_activation_config.json"
    write_id_file(ids_file, ids)
    write_gui_config(config_file, ids_file)

    summary = {
        "threshold": args.threshold,
        "prediction_files": [str(path) for path in prediction_files],
        "false_activation_rows": len(rows),
        "unique_instances": len(ids),
        "by_top_family": dict(Counter(row["top_family"] for row in rows)),
        "output_dir": str(output_dir),
        "gui_config": str(config_file),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
