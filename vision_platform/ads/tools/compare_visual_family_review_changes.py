from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


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


def normalize_family_text(value: str) -> str:
    parts = sorted(part.strip() for part in (value or "").replace("|", ";").split(";") if part.strip())
    return ";".join(parts)


def family_set(value: str) -> set[str]:
    return {part.strip() for part in (value or "").replace("|", ";").split(";") if part.strip()}


def load_current_visual_reviews(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT instance_id, families FROM visual_family_reviews").fetchall()
        return {row["instance_id"]: normalize_family_text(row["families"] or "") for row in rows}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a visual-family mismatch review batch with current DB labels.")
    parser.add_argument("--mismatches", default="vision_platform/ads/pilot/visual_family_smoke/review_mismatches/prediction_mismatches.csv")
    parser.add_argument("--db", default="vision_platform/vision_assets/review/vision_review.db")
    parser.add_argument("--output-dir", default="vision_platform/ads/pilot/visual_family_smoke/review_mismatches/after_review_compare")
    args = parser.parse_args()

    mismatch_rows = read_csv(Path(args.mismatches))
    current = load_current_visual_reviews(Path(args.db))
    by_instance: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in mismatch_rows:
        by_instance[row["instance_id"]].append(row)

    rows: list[dict[str, Any]] = []
    changed_rows: list[dict[str, Any]] = []
    for instance_id, items in sorted(by_instance.items()):
        first = items[0]
        before = normalize_family_text(first.get("current_db_families", ""))
        after = normalize_family_text(current.get(instance_id, ""))
        before_set = family_set(before)
        after_set = family_set(after)
        mismatch_summary = []
        fixed_summary = []
        still_mismatch_summary = []
        for item in items:
            family = item["family"]
            predicted = item["predicted_value"] == "1"
            was_true = item["true_value"] == "1"
            is_true_now = family in after_set
            mismatch_summary.append(f"{item['seed']}:{item['mismatch_type']}:{family}:p={item['score']}")
            if is_true_now == predicted:
                fixed_summary.append(f"{item['seed']}:{family}")
            if is_true_now != predicted:
                still_mismatch_summary.append(f"{item['seed']}:{family}")
        row = {
            "instance_id": instance_id,
            "content_id": first.get("content_id", ""),
            "relative_path": first.get("relative_path", ""),
            "before_families": before,
            "after_families": after,
            "changed": int(before != after),
            "added_families": ";".join(sorted(after_set - before_set)),
            "removed_families": ";".join(sorted(before_set - after_set)),
            "mismatch_count": len(items),
            "fixed_against_prediction_count": len(fixed_summary),
            "still_mismatch_against_prediction_count": len(still_mismatch_summary),
            "mismatches": " | ".join(mismatch_summary),
            "fixed_against_prediction": " | ".join(fixed_summary),
            "still_mismatch_against_prediction": " | ".join(still_mismatch_summary),
        }
        rows.append(row)
        if row["changed"]:
            changed_rows.append(row)

    output_dir = Path(args.output_dir)
    fieldnames = [
        "instance_id",
        "content_id",
        "relative_path",
        "before_families",
        "after_families",
        "changed",
        "added_families",
        "removed_families",
        "mismatch_count",
        "fixed_against_prediction_count",
        "still_mismatch_against_prediction_count",
        "mismatches",
        "fixed_against_prediction",
        "still_mismatch_against_prediction",
    ]
    write_csv(output_dir / "review_change_comparison.csv", rows, fieldnames)
    write_csv(output_dir / "changed_only.csv", changed_rows, fieldnames)
    summary = {
        "reviewed_instances_in_batch": len(rows),
        "changed_instances": len(changed_rows),
        "unchanged_instances": len(rows) - len(changed_rows),
        "fixed_against_prediction_total": sum(int(row["fixed_against_prediction_count"]) for row in rows),
        "still_mismatch_against_prediction_total": sum(int(row["still_mismatch_against_prediction_count"]) for row in rows),
        "changed_added_family_counts": Counter(
            family
            for row in changed_rows
            for family in str(row["added_families"]).split(";")
            if family
        ),
        "changed_removed_family_counts": Counter(
            family
            for row in changed_rows
            for family in str(row["removed_families"]).split(";")
            if family
        ),
        "output_dir": str(output_dir),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
