from __future__ import annotations

import argparse
import csv
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


REVIEW_FOLDERS = {
    "pending": ("", "pending"),
    "close": ("close", "reviewed"),
    "not_close": ("not_close", "reviewed"),
    "uncertain": ("uncertain", "reviewed"),
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}


def candidate_id_from_path(path: Path) -> str:
    return path.stem


def read_manifest(path: Path) -> tuple[list[dict], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def scan_review_dir(review_dir: Path) -> dict[str, tuple[str, str, Path]]:
    locations: dict[str, list[tuple[str, str, Path]]] = defaultdict(list)
    duplicate_names = []
    for folder, (label, status) in REVIEW_FOLDERS.items():
        directory = review_dir / folder
        if not directory.exists():
            raise SystemExit(f"missing review folder: {directory}")
        seen_in_folder = set()
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                continue
            candidate_id = candidate_id_from_path(path)
            if candidate_id in seen_in_folder:
                duplicate_names.append(str(path))
            seen_in_folder.add(candidate_id)
            locations[candidate_id].append((label, status, path))

    conflicts = {cid: values for cid, values in locations.items() if len(values) > 1}
    if conflicts or duplicate_names:
        lines = []
        if conflicts:
            lines.append("candidate appears in multiple review folders:")
            for cid, values in sorted(conflicts.items()):
                places = ", ".join(str(path) for _label, _status, path in values)
                lines.append(f"  {cid}: {places}")
        if duplicate_names:
            lines.append("duplicate filename found:")
            lines.extend(f"  {path}" for path in duplicate_names)
        raise SystemExit("\n".join(lines))

    return {cid: values[0] for cid, values in locations.items()}


def sync_labels(manifest: Path, review_dir: Path, output: Path | None):
    rows, fieldnames = read_manifest(manifest)
    for field in ("label", "review_status"):
        if field not in fieldnames:
            fieldnames.append(field)

    manifest_ids = [row.get("candidate_id") or Path(row.get("image_path", "")).stem for row in rows]
    duplicate_manifest = [cid for cid, count in Counter(manifest_ids).items() if count > 1]
    if duplicate_manifest:
        raise SystemExit("duplicate candidate_id in manifest:\n" + "\n".join(f"  {cid}" for cid in duplicate_manifest))

    manifest_set = set(manifest_ids)
    locations = scan_review_dir(review_dir)
    unknown = sorted(set(locations) - manifest_set)
    missing = sorted(manifest_set - set(locations))
    if unknown or missing:
        lines = []
        if unknown:
            lines.append("review files not found in manifest:")
            lines.extend(f"  {cid}" for cid in unknown[:50])
        if missing:
            lines.append("manifest candidates missing from review folders:")
            lines.extend(f"  {cid}" for cid in missing[:50])
        raise SystemExit("\n".join(lines))

    stats = Counter()
    for row, candidate_id in zip(rows, manifest_ids):
        label, status, _path = locations[candidate_id]
        row["label"] = label
        row["review_status"] = status
        stats[label or "pending"] += 1

    target = output or manifest
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    Path(tmp_name).replace(target)

    print(f"wrote: {target}")
    for key in ("pending", "close", "not_close", "uncertain"):
        print(f"{key}: {stats[key]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    sync_labels(args.manifest, args.review_dir, args.output)


if __name__ == "__main__":
    main()
