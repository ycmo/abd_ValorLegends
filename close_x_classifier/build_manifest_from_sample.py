from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}


def candidate_score(path: Path) -> str:
    match = re.search(r"score_([0-9.]+)", path.name)
    return match.group(1).rstrip(".") if match else ""


def infer_source_session(path: Path) -> str:
    name = path.stem
    match = re.search(r"(20\d{6}_\d{6}_[^_]+)", name)
    if match:
        return match.group(1)
    match = re.search(r"log__(.+?)(__\d{6}_|\Z)", name)
    if match:
        return match.group(1)[:80]
    return "unknown_session"


def infer_ad_source(path: Path) -> str:
    name = path.stem.lower()
    for token in ("google", "unity", "applovin", "facebook", "pangle", "vungle"):
        if token in name:
            return token
    return "unknown_ad_source"


def infer_icon_family(path: Path, label: str) -> str:
    if label == "close":
        stem = path.stem
        if stem.startswith("close_"):
            return stem
        if stem.startswith("ad_issue_"):
            return stem.rsplit("_roi_", 1)[0]
        return "positive_unknown_family"
    return "negative_unknown_family"


def iter_images(root: Path):
    if not root.exists():
        return
    yield from sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def write_manifest(positive_dir: Path, negative_dir: Path, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for label, directory in (("close", positive_dir), ("not_close", negative_dir)):
        for path in iter_images(directory):
            rows.append(
                {
                    "image_path": str(path.resolve()),
                    "label": label,
                    "source_session": infer_source_session(path),
                    "ad_source": infer_ad_source(path),
                    "icon_family": infer_icon_family(path, label),
                    "candidate_score": candidate_score(path),
                }
            )

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image_path",
                "label",
                "source_session",
                "ad_source",
                "icon_family",
                "candidate_score",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows: {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--positive-dir",
        type=Path,
        default=Path("ads2/assets/review_crops/close_glyph_candidates/sample/x_rule_calibration/samples"),
    )
    parser.add_argument(
        "--negative-dir",
        type=Path,
        default=Path("ads2/assets/review_crops/close_glyph_candidates/sample/reject_candidates"),
    )
    parser.add_argument("--output", type=Path, default=Path("close_x_classifier/data/manifest.csv"))
    args = parser.parse_args()
    write_manifest(args.positive_dir, args.negative_dir, args.output)


if __name__ == "__main__":
    main()
