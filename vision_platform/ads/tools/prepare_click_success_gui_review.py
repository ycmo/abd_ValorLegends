from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


FAMILIES = ["x_mark", "play_triangle", "google_play", "next", "free", "got", "arrow"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def ensure_suggestion_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS visual_family_model_suggestions (
            instance_id TEXT PRIMARY KEY REFERENCES assets(instance_id) ON DELETE CASCADE,
            families TEXT NOT NULL DEFAULT '',
            probabilities_json TEXT NOT NULL DEFAULT '{}',
            model_name TEXT NOT NULL DEFAULT '',
            checkpoint_path TEXT NOT NULL DEFAULT '',
            assignment_policy TEXT NOT NULL DEFAULT '',
            threshold REAL NOT NULL DEFAULT 0,
            uncertain_low REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Ads family GUI config for selected click-success scan rows.")
    parser.add_argument("--review-needed", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    con = sqlite3.connect(str(args.db))
    con.row_factory = sqlite3.Row
    ensure_suggestion_table(con)
    now = utc_now()

    output_rows: list[dict[str, str]] = []
    missing: list[str] = []
    for row in read_csv(args.review_needed):
        bbox_crop = str(Path(row["bbox_crop"]).resolve())
        asset = con.execute(
            "SELECT instance_id, content_id, relative_path FROM assets WHERE original_path = ?",
            (bbox_crop,),
        ).fetchone()
        if asset is None:
            missing.append(bbox_crop)
            continue
        probs = {family: float(row.get(f"p_{family}") or 0.0) for family in FAMILIES}
        suggestion = row.get("top_family") or max(probs, key=probs.get)
        con.execute(
            """
            INSERT INTO visual_family_model_suggestions(
                instance_id, families, probabilities_json, model_name, checkpoint_path,
                assignment_policy, threshold, uncertain_low, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
                families=excluded.families,
                probabilities_json=excluded.probabilities_json,
                model_name=excluded.model_name,
                checkpoint_path=excluded.checkpoint_path,
                assignment_policy=excluded.assignment_policy,
                threshold=excluded.threshold,
                uncertain_low=excluded.uncertain_low,
                updated_at=excluded.updated_at
            """,
            (
                asset["instance_id"],
                suggestion,
                json.dumps(probs, ensure_ascii=False),
                "visual_family_epochs20_ensemble_click_success_scan",
                "seed42+seed43+seed44 mean",
                "top1",
                0.5,
                0.0,
                now,
                now,
            ),
        )
        output_rows.append(
            {
                **row,
                "instance_id": asset["instance_id"],
                "content_id": asset["content_id"],
                "relative_path": asset["relative_path"],
                "suggestion_family": suggestion,
            }
        )
    con.commit()
    con.close()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    instances_csv = args.output_dir / "review_needed_instances.csv"
    config_path = args.output_dir / "ads_family_review_gui_click_success_review_config.json"
    fields = [
        "instance_id",
        "content_id",
        "relative_path",
        "event_id",
        "review_reasons",
        "proposal_source",
        "template_name",
        "expected_family",
        "expected_p",
        "top_family",
        "top_p",
        "suggestion_family",
        "bbox_crop",
    ]
    write_csv(instances_csv, output_rows, fields)
    config = {
        "instance_list_csv": str(instances_csv),
        "instance_list_column": "instance_id",
        "default_filter": {
            "status": "all",
            "family": "all",
            "source": "all",
            "path_contains": "",
            "search": "",
            "sort": "review_list",
            "selection_mode": "single",
            "default_pick": "model suggestion",
        },
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "review_needed": str(args.review_needed),
        "input_rows": len(read_csv(args.review_needed)),
        "matched_instances": len(output_rows),
        "missing": missing,
        "instances_csv": str(instances_csv),
        "config": str(config_path),
    }
    (args.output_dir / "gui_review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
