from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


def read_rows(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def stable_score(*parts) -> int:
    text = "\x1f".join(str(part) for part in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def write_rows(path: Path, rows: list[dict]):
    fieldnames = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def choose_negative_test_sessions(rows: list[dict], ratio: float, seed: int) -> set[str]:
    negative_sessions = sorted({row["source_session"] for row in rows if row["label"] == "not_close"})
    scored = sorted((stable_score(session, seed), session) for session in negative_sessions)
    count = max(1, round(len(scored) * ratio))
    return {session for _score, session in scored[:count]}


def assign_fold_splits(
    rows: list[dict],
    heldout_positive: dict,
    negative_test_sessions: set[str],
    val_positive_count: int,
    val_negative_session_ratio: float,
    seed: int,
) -> list[dict]:
    positives = [row for row in rows if row["label"] == "close" and row["image_path"] != heldout_positive["image_path"]]
    val_positives = {row["image_path"] for row in sorted(positives, key=lambda row: stable_score(row["original_name"], seed))[:val_positive_count]}
    train_negative_sessions = sorted(
        {row["source_session"] for row in rows if row["label"] == "not_close" and row["source_session"] not in negative_test_sessions}
    )
    val_neg_count = max(1, round(len(train_negative_sessions) * val_negative_session_ratio))
    val_negative_sessions = {
        session
        for _score, session in sorted((stable_score(session, seed, "val"), session) for session in train_negative_sessions)[:val_neg_count]
    }

    output = []
    for row in rows:
        clone = dict(row)
        if row["label"] == "close":
            clone["source_session"] = f"positive_object::{row['original_name']}"
            if row["image_path"] == heldout_positive["image_path"]:
                clone["split"] = "test"
            elif row["image_path"] in val_positives:
                clone["split"] = "val"
            else:
                clone["split"] = "train"
        else:
            session = row["source_session"]
            if session in negative_test_sessions:
                clone["split"] = "test"
            elif session in val_negative_sessions:
                clone["split"] = "val"
            else:
                clone["split"] = "train"
        output.append(clone)
    return output


def split_counts(rows: list[dict]) -> dict[str, dict[str, int]]:
    counts = defaultdict(Counter)
    for row in rows:
        counts[row["split"]][row["label"]] += 1
    return {split: dict(counter) for split, counter in sorted(counts.items())}


def run_train(repo_root: Path, manifest: Path, output_dir: Path, seed: int, epochs: int, batch_size: int, device: str):
    cmd = [
        str(repo_root / ".venv-codex" / "Scripts" / "python.exe"),
        str(repo_root / "close_x_classifier" / "train.py"),
        "--manifest",
        str(manifest),
        "--output-dir",
        str(output_dir),
        "--epochs",
        str(epochs),
        "--batch-size",
        str(batch_size),
        "--device",
        device,
        "--seed",
        str(seed),
    ]
    subprocess.run(cmd, cwd=repo_root, check=True)


def read_predictions(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def summarize_fold(run_dir: Path, heldout_positive: dict, threshold: float) -> dict:
    predictions = read_predictions(run_dir / "predictions.csv")
    heldout = None
    false_positives = []
    tn = fp = 0
    for row in predictions:
        p_close = float(row["p_close"])
        if row["label"] == "close" and Path(row["image_path"]).name == Path(heldout_positive["image_path"]).name:
            heldout = row
        if row["label"] == "not_close":
            if p_close >= threshold:
                fp += 1
                false_positives.append(row)
            else:
                tn += 1
    if heldout is None:
        raise RuntimeError(f"held-out positive missing from predictions: {heldout_positive['original_name']}")
    p_heldout = float(heldout["p_close"])
    return {
        "heldout_original_name": heldout_positive["original_name"],
        "heldout_image": heldout_positive["image_path"],
        "heldout_p_close": p_heldout,
        "heldout_pass": int(p_heldout >= threshold),
        "negative_tn": tn,
        "negative_fp": fp,
        "false_positives": false_positives,
    }


def inspect_crop_style(rows: list[dict]) -> dict[str, dict[str, int]]:
    by_type = defaultdict(Counter)
    for row in rows:
        by_type[row["label"]][row.get("source_type", "")] += 1
    return {label: dict(counter) for label, counter in by_type.items()}


def write_summary(summary_rows: list[dict], output: Path):
    fieldnames = [
        "fold",
        "heldout_original_name",
        "heldout_p_close",
        "heldout_pass",
        "negative_tn",
        "negative_fp",
        "false_positive_count",
        "false_positive_original_names",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("close_x_classifier/data/stage0_object_poc/manifest.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("close_x_classifier/runs/stage0_5_lopo"))
    parser.add_argument("--negative-test-ratio", type=float, default=0.2)
    parser.add_argument("--negative-test-sessions-json", type=Path, default=None)
    parser.add_argument("--val-negative-session-ratio", type=float, default=0.2)
    parser.add_argument("--val-positive-count", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260711)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    repo_root = Path.cwd()
    rows = read_rows(args.manifest)
    positives = [row for row in rows if row["label"] == "close"]
    negatives = [row for row in rows if row["label"] == "not_close"]
    if args.negative_test_sessions_json:
        loaded = json.loads(args.negative_test_sessions_json.read_text(encoding="utf-8"))
        negative_test_sessions = set(loaded["negative_test_sessions"] if isinstance(loaded, dict) else loaded)
    else:
        negative_test_sessions = choose_negative_test_sessions(rows, args.negative_test_ratio, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    crop_style = inspect_crop_style(rows)
    print("crop_style:", crop_style)
    print("negative_test_sessions:", sorted(negative_test_sessions))
    print("positive_count:", len(positives), "negative_count:", len(negatives))

    fold_summaries = []
    fp_counter = Counter()
    fp_detail = {}
    for fold_index, positive in enumerate(positives, start=1):
        fold_dir = args.output_dir / f"fold_{fold_index:02d}"
        fold_manifest = fold_dir / "manifest.csv"
        fold_rows = assign_fold_splits(
            rows,
            positive,
            negative_test_sessions,
            args.val_positive_count,
            args.val_negative_session_ratio,
            args.seed + fold_index,
        )
        write_rows(fold_manifest, fold_rows)
        counts = split_counts(fold_rows)
        print(f"fold={fold_index:02d} heldout={positive['original_name']} split_counts={counts}")
        run_train(repo_root, fold_manifest, fold_dir, args.seed + fold_index, args.epochs, args.batch_size, args.device)
        fold_summary = summarize_fold(fold_dir, positive, args.threshold)
        for fp in fold_summary["false_positives"]:
            original = fp.get("original_name") or Path(fp["image_path"]).name
            fp_counter[original] += 1
            fp_detail[original] = fp
        fold_summaries.append(
            {
                "fold": fold_index,
                "heldout_original_name": fold_summary["heldout_original_name"],
                "heldout_p_close": f"{fold_summary['heldout_p_close']:.6f}",
                "heldout_pass": fold_summary["heldout_pass"],
                "negative_tn": fold_summary["negative_tn"],
                "negative_fp": fold_summary["negative_fp"],
                "false_positive_count": len(fold_summary["false_positives"]),
                "false_positive_original_names": ";".join(
                    (fp.get("original_name") or Path(fp["image_path"]).name) for fp in fold_summary["false_positives"]
                ),
            }
        )

    write_summary(fold_summaries, args.output_dir / "summary.csv")
    aggregate = {
        "folds": len(fold_summaries),
        "heldout_success": sum(int(row["heldout_pass"]) for row in fold_summaries),
        "heldout_fail": sum(1 - int(row["heldout_pass"]) for row in fold_summaries),
        "negative_fp_total": sum(int(row["negative_fp"]) for row in fold_summaries),
        "negative_tn_total": sum(int(row["negative_tn"]) for row in fold_summaries),
        "repeated_false_positives": fp_counter.most_common(),
        "crop_style": crop_style,
        "negative_test_sessions": sorted(negative_test_sessions),
    }
    (args.output_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(aggregate, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
