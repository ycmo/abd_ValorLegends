from __future__ import annotations

import argparse
import csv
import random
import warnings
from collections import Counter, defaultdict
from pathlib import Path


def split_key(row: dict) -> str:
    return row.get("source_session") or "unknown_session"


def read_rows(path: Path) -> tuple[list[dict], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_rows(path: Path, rows: list[dict], fieldnames: list[str]):
    if "split" not in fieldnames:
        fieldnames.append("split")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def validate_no_session_split(rows: list[dict]):
    sessions = defaultdict(set)
    for row in rows:
        sessions[row.get("source_session") or "unknown_session"].add(row.get("split") or "")
    conflicts = {session: sorted(splits) for session, splits in sessions.items() if len(splits) > 1}
    if conflicts:
        lines = ["source_session split leakage detected:"]
        for session, splits in sorted(conflicts.items()):
            lines.append(f"  {session}: {', '.join(splits)}")
        raise SystemExit("\n".join(lines))


def split_has_both_classes(rows: list[dict]) -> bool:
    labels = {row.get("label", "") for row in rows if row.get("label", "") in ("close", "not_close")}
    return labels == {"close", "not_close"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows, fieldnames = read_rows(args.manifest)
    groups = defaultdict(list)
    for row in rows:
        groups[split_key(row)].append(row)

    group_keys = list(groups)
    random.Random(args.seed).shuffle(group_keys)
    n = len(group_keys)
    n_test = max(1, round(n * args.test_ratio)) if n >= 3 else 0
    n_val = max(1, round(n * args.val_ratio)) if n - n_test >= 2 else 0
    test_groups = set(group_keys[:n_test])
    val_groups = set(group_keys[n_test : n_test + n_val])

    split_counts = Counter()
    label_counts = Counter()
    for key, items in groups.items():
        split = "test" if key in test_groups else "val" if key in val_groups else "train"
        for row in items:
            row["split"] = split
            split_counts[split] += 1
            label_counts[(split, row.get("label", ""))] += 1

    validate_no_session_split(rows)
    write_rows(args.output, rows, fieldnames)
    split_rows = defaultdict(list)
    for row in rows:
        split_rows[row.get("split", "")].append(row)
    for name in ("val", "test"):
        if split_rows[name] and not split_has_both_classes(split_rows[name]):
            warnings.warn(f"{name} split does not contain both close and not_close labels", RuntimeWarning)
    print(f"wrote: {args.output}")
    print("split counts:", dict(split_counts))
    print("label counts:", {f"{split}:{label}": count for (split, label), count in sorted(label_counts.items())})


if __name__ == "__main__":
    main()
