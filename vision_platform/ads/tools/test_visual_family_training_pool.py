from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path
from types import SimpleNamespace

from prepare_visual_family_training_pool import prepare_pool
from train_visual_family_smoke import assign_splits, read_manifest


FAMILIES = [
    "x_mark",
    "play_triangle",
    "google_play",
    "next",
    "free",
    "got",
    "arrow",
]


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "image_path",
        "families",
        *[f"label_{family}" for family in FAMILIES],
        "review_status",
        "group_key",
        "source_screen",
        "instance_id",
        "content_id",
        "original_path",
        "relative_path",
        "vision_domain",
        "asset_type",
        "asset_role",
        "image_scope",
        "representation",
        "source_root",
        "split",
        "is_confirmed_strong_hard_negative",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            full = {field: "" for field in fields}
            full.update(row)
            writer.writerow(full)


def base_row(**updates: str) -> dict[str, str]:
    row = {
        "image_path": "dummy.png",
        "families": "negative",
        "label_x_mark": "0",
        "label_play_triangle": "0",
        "label_google_play": "0",
        "label_next": "0",
        "label_free": "0",
        "label_got": "0",
        "label_arrow": "0",
        "review_status": "reviewed",
        "group_key": "group_a",
        "source_screen": "",
        "instance_id": "file_a",
        "content_id": "asset_a",
        "original_path": "dummy.png",
        "relative_path": "dummy.png",
        "vision_domain": "ads",
        "asset_type": "crop",
        "asset_role": "candidate_crop",
        "image_scope": "crop",
        "representation": "raw",
        "source_root": "synthetic",
        "split": "",
        "is_confirmed_strong_hard_negative": "0",
    }
    row.update(updates)
    return row


def expect_failure(name: str, func) -> str:
    try:
        func()
    except SystemExit as exc:
        return f"PASS {name}: {exc}"
    raise AssertionError(f"FAIL {name}: expected SystemExit")


def test_same_content_cross_split(tmp: Path) -> str:
    manifest = tmp / "same_content.csv"
    write_manifest(
        manifest,
        [
            base_row(instance_id="file_1", content_id="asset_same", group_key="group_1", split="train"),
            base_row(instance_id="file_2", content_id="asset_same", group_key="group_2", split="test"),
        ],
    )
    return expect_failure("same_content_cross_split", lambda: assign_splits(read_manifest(manifest), 42, 0.2, 0.2))


def test_same_group_cross_split(tmp: Path) -> str:
    manifest = tmp / "same_group.csv"
    write_manifest(
        manifest,
        [
            base_row(instance_id="file_1", content_id="asset_1", group_key="group_same", split="train"),
            base_row(instance_id="file_2", content_id="asset_2", group_key="group_same", split="test"),
        ],
    )
    return expect_failure("same_group_key_cross_split", lambda: assign_splits(read_manifest(manifest), 42, 0.2, 0.2))


def write_false_activation(path: Path, content_ids: list[str]) -> None:
    fields = ["seed", "instance_id", "content_id", "top_family"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, content_id in enumerate(content_ids):
            writer.writerow({"seed": "seed42", "instance_id": f"file_{index}", "content_id": content_id, "top_family": "x_mark"})


def test_hard_negative_positive_label(tmp: Path) -> str:
    manifest = tmp / "hard_positive.csv"
    false_csv = tmp / "false.csv"
    write_manifest(
        manifest,
        [
            base_row(
                instance_id="file_1",
                content_id="asset_hard",
                families="x_mark",
                label_x_mark="1",
            )
        ],
    )
    write_false_activation(false_csv, ["asset_hard"])
    return expect_failure(
        "hard_negative_positive_family_label",
        lambda: prepare_pool(SimpleNamespace(manifest=manifest, false_activation_csv=false_csv, output_dir=tmp / "out_hard", overwrite=True)),
    )


def test_missing_hard_negative(tmp: Path) -> str:
    manifest = tmp / "missing.csv"
    false_csv = tmp / "false_missing.csv"
    write_manifest(manifest, [base_row(instance_id="file_1", content_id="asset_present")])
    write_false_activation(false_csv, ["asset_missing"])
    return expect_failure(
        "missing_confirmed_hard_negative_content",
        lambda: prepare_pool(SimpleNamespace(manifest=manifest, false_activation_csv=false_csv, output_dir=tmp / "out_missing", overwrite=True)),
    )


def test_deterministic_assignments(manifest: Path) -> str:
    first_rows = read_manifest(manifest)
    second_rows = read_manifest(manifest)
    assign_splits(first_rows, 42, 0.2, 0.2)
    assign_splits(second_rows, 42, 0.2, 0.2)
    first = [(row.instance_id, row.content_id, row.group_key, row.split) for row in first_rows]
    second = [(row.instance_id, row.content_id, row.group_key, row.split) for row in second_rows]
    if first != second:
        raise AssertionError("FAIL deterministic_assignments: assignments differ")
    return f"PASS deterministic_assignments: {len(first)} rows"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/training_pool/manifest.csv"))
    parser.add_argument("--tmp-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/training_pool_tests_tmp"))
    args = parser.parse_args()

    if args.tmp_dir.exists():
        shutil.rmtree(args.tmp_dir)
    args.tmp_dir.mkdir(parents=True, exist_ok=True)

    results = [
        test_same_content_cross_split(args.tmp_dir),
        test_same_group_cross_split(args.tmp_dir),
        test_hard_negative_positive_label(args.tmp_dir),
        test_missing_hard_negative(args.tmp_dir),
        test_deterministic_assignments(args.manifest),
    ]
    report = "\n".join(results) + "\n"
    (args.tmp_dir / "test_results.txt").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
