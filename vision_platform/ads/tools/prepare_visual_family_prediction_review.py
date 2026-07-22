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


def build_rows(prediction_files: list[Path], threshold: float, db_families: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pred_path in prediction_files:
        seed = seed_name(pred_path)
        for raw in read_csv(pred_path):
            instance_id = raw.get("instance_id", "")
            original_families = raw.get("families", "")
            current_families = db_families.get(instance_id, "")
            for family in FAMILIES:
                true_value = int(float(raw.get(f"true_{family}") or 0))
                score = float(raw.get(f"p_{family}") or 0.0)
                predicted = int(score >= threshold)
                if true_value == predicted:
                    continue
                mismatch_type = "false_positive" if predicted and not true_value else "false_negative"
                rows.append(
                    {
                        "seed": seed,
                        "mismatch_type": mismatch_type,
                        "family": family,
                        "score": f"{score:.5f}",
                        "threshold": threshold,
                        "true_value": true_value,
                        "predicted_value": predicted,
                        "instance_id": instance_id,
                        "content_id": raw.get("content_id", ""),
                        "relative_path": raw.get("relative_path", ""),
                        "dataset_image_path": raw.get("image_path", ""),
                        "original_families": original_families,
                        "current_db_families": current_families,
                    }
                )
    return rows


def write_id_file(path: Path, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")


def write_gui_config(path: Path, ids_file: Path, visual_status: str = "all") -> None:
    config = {
        "default_filter": {
            "domain": "ads_shared",
            "role": "all",
            "scope": "crop",
            "source": "all",
            "status": "all",
            "visual_status": visual_status,
            "search": "",
            "sort": "image_signature",
            "include_instance_ids_file": str(ids_file),
        },
        "sort_mode": "image_signature",
    }
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Visual Family FP/FN review lists for the review GUI.")
    parser.add_argument("--predictions-dir", default="vision_platform/ads/pilot/visual_family_smoke")
    parser.add_argument("--db", default="vision_platform/vision_assets/review/vision_review.db")
    parser.add_argument("--output-dir", default="vision_platform/ads/pilot/visual_family_smoke/review_mismatches")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    predictions_dir = Path(args.predictions_dir)
    output_dir = Path(args.output_dir)
    prediction_files = prediction_paths(predictions_dir)
    if not prediction_files:
        raise SystemExit(f"No test_predictions.csv files found under {predictions_dir}")

    db_families = load_current_visual_reviews(Path(args.db))
    rows = build_rows(prediction_files, args.threshold, db_families)
    output_dir.mkdir(parents=True, exist_ok=True)

    unique_by_type: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        unique_by_type["all_mismatches"].add(row["instance_id"])
        unique_by_type[row["mismatch_type"]].add(row["instance_id"])

    fieldnames = [
        "seed",
        "mismatch_type",
        "family",
        "score",
        "threshold",
        "true_value",
        "predicted_value",
        "instance_id",
        "content_id",
        "relative_path",
        "dataset_image_path",
        "original_families",
        "current_db_families",
    ]
    write_csv(output_dir / "prediction_mismatches.csv", rows, fieldnames)

    for name in ["all_mismatches", "false_positive", "false_negative"]:
        ids = sorted(unique_by_type.get(name, set()))
        ids_file = output_dir / f"{name}_instance_ids.txt"
        config_file = output_dir / f"review_gui_{name}_config.json"
        write_id_file(ids_file, ids)
        write_gui_config(config_file, ids_file)

    family_counter = Counter((row["mismatch_type"], row["family"]) for row in rows)
    summary = {
        "threshold": args.threshold,
        "prediction_files": [str(path) for path in prediction_files],
        "mismatch_rows": len(rows),
        "unique_all_mismatches": len(unique_by_type["all_mismatches"]),
        "unique_false_positive": len(unique_by_type["false_positive"]),
        "unique_false_negative": len(unique_by_type["false_negative"]),
        "mismatches_by_type_family": {
            f"{kind}:{family}": count for (kind, family), count in sorted(family_counter.items())
        },
        "output_dir": str(output_dir),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
