from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
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
        writer.writerows(rows)


def load_confirmed_hard_negatives(false_activation_csv: Path) -> tuple[set[str], list[dict[str, str]]]:
    rows = read_csv(false_activation_csv)
    content_ids = {row["content_id"].strip() for row in rows if row.get("content_id", "").strip()}
    return content_ids, rows


def is_none_of_the_above(row: dict[str, str]) -> bool:
    return all(int(float(row.get(f"label_{family}") or 0)) == 0 for family in FAMILIES)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_pool(args: argparse.Namespace) -> None:
    output_dir: Path = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = read_csv(args.manifest)
    hard_content_ids, false_activation_rows = load_confirmed_hard_negatives(args.false_activation_csv)

    content_to_manifest_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in manifest_rows:
        content_to_manifest_rows[row.get("content_id", "")].append(row)

    missing_hard_contents = sorted(content_id for content_id in hard_content_ids if content_id not in content_to_manifest_rows)
    if missing_hard_contents:
        raise SystemExit(f"confirmed hard-negative content missing from manifest: {missing_hard_contents[:20]}")

    positive_hard_rows = [
        row
        for content_id in hard_content_ids
        for row in content_to_manifest_rows.get(content_id, [])
        if not is_none_of_the_above(row)
    ]
    if positive_hard_rows:
        sample = [
            {
                "instance_id": row.get("instance_id", ""),
                "content_id": row.get("content_id", ""),
                "families": row.get("families", ""),
            }
            for row in positive_hard_rows[:20]
        ]
        raise SystemExit(f"confirmed hard-negative content has positive family label: {sample}")

    non_negative_hard_rows = []
    output_rows: list[dict[str, Any]] = []
    split_counts = Counter()
    family_counts = Counter()
    hard_rows = 0
    hard_instances: list[dict[str, Any]] = []

    for row in manifest_rows:
        row = dict(row)
        content_id = row.get("content_id", "")
        none_of_above = is_none_of_the_above(row)
        is_hard = content_id in hard_content_ids
        if is_hard and not none_of_above:
            non_negative_hard_rows.append(row)
            raise SystemExit(
                "confirmed hard-negative row has positive family label: "
                f"instance_id={row.get('instance_id', '')}; content_id={content_id}; families={row.get('families', '')}"
            )

        if is_hard:
            # These were manually confirmed after model false activation review.
            # Force them into train for the development training pool; this is
            # not a clean holdout split.
            row["split"] = "train"
            hard_rows += 1
            hard_instances.append(
                {
                    "instance_id": row.get("instance_id", ""),
                    "content_id": content_id,
                    "relative_path": row.get("relative_path", ""),
                    "image_path": row.get("image_path", ""),
                    "families": row.get("families", ""),
                    "source_screen": row.get("source_screen", ""),
                    "group_key": row.get("group_key", ""),
                }
            )

        row["pool_status"] = "trainable"
        row["pool_role"] = "visual_family_training_pool"
        row["is_none_of_the_above"] = int(none_of_above)
        row["is_confirmed_strong_hard_negative"] = int(is_hard)
        row["hard_negative_source"] = "none_of_the_above_false_activation_review" if is_hard else ""
        row["evaluation_status"] = "development_pool_not_final_holdout"
        output_rows.append(row)

        split_counts[row.get("split", "") or "auto"] += 1
        for family in (row.get("families") or "").split("|"):
            if family:
                family_counts[family] += 1

    fieldnames = list(manifest_rows[0].keys()) if manifest_rows else []
    for extra in [
        "pool_status",
        "pool_role",
        "is_none_of_the_above",
        "is_confirmed_strong_hard_negative",
        "hard_negative_source",
        "evaluation_status",
    ]:
        if extra not in fieldnames:
            fieldnames.append(extra)
    write_csv(output_dir / "manifest.csv", output_rows, fieldnames)
    write_csv(
        output_dir / "confirmed_strong_hard_negative_instances.csv",
        hard_instances,
        [
            "instance_id",
            "content_id",
            "relative_path",
            "image_path",
            "families",
            "source_screen",
            "group_key",
        ],
    )
    (output_dir / "confirmed_strong_hard_negative_content_ids.txt").write_text(
        "\n".join(sorted(hard_content_ids)) + ("\n" if hard_content_ids else ""),
        encoding="utf-8",
    )

    triggered_by_family = Counter(row.get("top_family", "") for row in false_activation_rows if row.get("top_family", ""))
    summary = {
        "source_manifest": str(args.manifest),
        "source_manifest_sha256": sha256_file(args.manifest),
        "false_activation_csv": str(args.false_activation_csv),
        "false_activation_csv_sha256": sha256_file(args.false_activation_csv),
        "tool_sha256": sha256_file(Path(__file__)),
        "rows": len(output_rows),
        "families": FAMILIES,
        "family_counts": dict(family_counts),
        "none_of_the_above_rows": sum(1 for row in output_rows if row["is_none_of_the_above"]),
        "confirmed_strong_hard_negative_contents": len(hard_content_ids),
        "confirmed_strong_hard_negative_rows": hard_rows,
        "confirmed_strong_hard_negative_instances": len(hard_instances),
        "missing_hard_negative_contents": missing_hard_contents,
        "non_negative_hard_rows": len(non_negative_hard_rows),
        "split_counts_in_manifest": dict(split_counts),
        "false_activation_rows": len(false_activation_rows),
        "false_activation_unique_instances": len({row.get("instance_id", "") for row in false_activation_rows}),
        "false_activation_triggered_by_family": dict(triggered_by_family),
        "evaluation_status": "development_pool_not_final_holdout",
        "manifest": str(output_dir / "manifest.csv"),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Visual Family Training Pool",
        "",
        "This is a development training pool, not a final generalization holdout.",
        "",
        f"- Source manifest: `{args.manifest}`",
        f"- Rows: {summary['rows']}",
        f"- None-of-the-above rows: {summary['none_of_the_above_rows']}",
        f"- Confirmed strong hard-negative contents: {summary['confirmed_strong_hard_negative_contents']}",
        f"- Confirmed strong hard-negative rows fixed to train: {summary['confirmed_strong_hard_negative_rows']}",
        f"- Missing hard-negative contents: {len(missing_hard_contents)}",
        f"- Non-negative hard rows rejected: {len(non_negative_hard_rows)}",
        "",
        "## Family Counts",
        "",
    ]
    for family, count in sorted(family_counts.items()):
        lines.append(f"- {family}: {count}")
    lines.extend(
        [
            "",
            "## False Activation Source Families",
            "",
        ]
    )
    for family, count in sorted(triggered_by_family.items()):
        lines.append(f"- {family}: {count}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `negative` remains a human review label and is represented as all-zero official family labels.",
            "- Confirmed strong hard negatives are forced to `split=train` so they actually enter training.",
            "- A new chronological holdout must be collected separately and kept out of this pool.",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the Ads visual-family development training pool.")
    parser.add_argument("--manifest", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/dataset/manifest.csv"))
    parser.add_argument(
        "--false-activation-csv",
        type=Path,
        default=Path("vision_platform/ads/pilot/visual_family_smoke/none_of_the_above_review/none_of_the_above_false_activations.csv"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/training_pool"))
    parser.add_argument("--overwrite", action="store_true")
    prepare_pool(parser.parse_args())


if __name__ == "__main__":
    main()
