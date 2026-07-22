from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
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


def metric_for(rows: list[dict[str, str]], family: str, threshold: float) -> dict[str, float | int]:
    tp = fp = tn = fn = 0
    none_support = 0
    none_false_activation = 0
    for row in rows:
        true = int(float(row.get(f"true_{family}") or 0))
        prob = float(row.get(f"p_{family}") or 0.0)
        pred = int(prob >= threshold)
        all_zero = all(int(float(row.get(f"true_{candidate}") or 0)) == 0 for candidate in FAMILIES)
        if all_zero:
            none_support += 1
            if pred:
                none_false_activation += 1
        if true and pred:
            tp += 1
        elif (not true) and pred:
            fp += 1
        elif true and not pred:
            fn += 1
        else:
            tn += 1
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    return {
        "support": tp + fn,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "none_support": none_support,
        "none_false_activation": none_false_activation,
        "none_false_activation_rate": none_false_activation / max(none_support, 1),
    }


def round_metric(value: float | int) -> float | int:
    if isinstance(value, int):
        return value
    return round(float(value), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep per-family thresholds for visual-family smoke predictions.")
    parser.add_argument("--predictions-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/threshold_sweep"))
    parser.add_argument("--start", type=float, default=0.05)
    parser.add_argument("--stop", type=float, default=0.95)
    parser.add_argument("--step", type=float, default=0.05)
    args = parser.parse_args()

    prediction_files = prediction_paths(args.predictions_dir)
    if not prediction_files:
        raise SystemExit(f"No test_predictions.csv files found under {args.predictions_dir}")

    thresholds = []
    value = args.start
    while value <= args.stop + 1e-9:
        thresholds.append(round(value, 4))
        value += args.step

    sweep_rows: list[dict[str, Any]] = []
    best_by_seed: list[dict[str, Any]] = []
    seed_family_threshold_values: dict[tuple[str, str, float], list[dict[str, float | int]]] = defaultdict(list)
    all_rows_by_seed: dict[str, list[dict[str, str]]] = {}
    for path in prediction_files:
        seed = seed_name(path)
        rows = read_csv(path)
        all_rows_by_seed[seed] = rows
        for family in FAMILIES:
            best: dict[str, Any] | None = None
            for threshold in thresholds:
                metric = metric_for(rows, family, threshold)
                seed_family_threshold_values[(family, seed, threshold)].append(metric)
                output_row = {
                    "seed": seed,
                    "family": family,
                    "threshold": threshold,
                    **{key: round_metric(value) for key, value in metric.items()},
                }
                sweep_rows.append(output_row)
                candidate_key = (metric["f1"], metric["precision"], metric["recall"], -threshold)
                if best is None or candidate_key > best["_key"]:
                    best = {**output_row, "_key": candidate_key}
            assert best is not None
            best.pop("_key", None)
            best_by_seed.append(best)

    # Mean metrics per family/threshold across seeds.
    mean_rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        for threshold in thresholds:
            metrics = [metric_for(rows, family, threshold) for rows in all_rows_by_seed.values()]
            mean_row = {
                "family": family,
                "threshold": threshold,
            }
            for key in [
                "support",
                "tp",
                "fp",
                "tn",
                "fn",
                "precision",
                "recall",
                "f1",
                "none_support",
                "none_false_activation",
                "none_false_activation_rate",
            ]:
                mean_row[key] = round(mean(float(metric[key]) for metric in metrics), 4)
            mean_rows.append(mean_row)

    best_mean_rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        candidates = [row for row in mean_rows if row["family"] == family]
        best = max(candidates, key=lambda row: (row["f1"], row["precision"], row["recall"], -row["threshold"]))
        best_mean_rows.append(best)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "seed",
        "family",
        "threshold",
        "support",
        "tp",
        "fp",
        "tn",
        "fn",
        "precision",
        "recall",
        "f1",
        "none_support",
        "none_false_activation",
        "none_false_activation_rate",
    ]
    write_csv(args.output_dir / "threshold_sweep_by_seed.csv", sweep_rows, fields)
    write_csv(args.output_dir / "best_threshold_by_seed.csv", best_by_seed, fields)
    write_csv(args.output_dir / "threshold_sweep_mean.csv", mean_rows, fields[1:])
    write_csv(args.output_dir / "best_threshold_mean.csv", best_mean_rows, fields[1:])

    lines = [
        "# Visual Family Threshold Sweep",
        "",
        "Thresholds are selected by mean F1 across seeds. This is exploratory only.",
        "",
        "| family | threshold | support | precision | recall | f1 | fp | fn | none false activation rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in best_mean_rows:
        lines.append(
            f"| {row['family']} | {row['threshold']:.2f} | {row['support']:.1f} | {row['precision']:.3f} | "
            f"{row['recall']:.3f} | {row['f1']:.3f} | {row['fp']:.1f} | {row['fn']:.1f} | "
            f"{row['none_false_activation_rate']:.3f} |"
        )
    (args.output_dir / "threshold_sweep_report.md").write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "prediction_files": [str(path) for path in prediction_files],
        "thresholds": thresholds,
        "best_thresholds": {
            row["family"]: {
                "threshold": row["threshold"],
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
                "none_false_activation_rate": row["none_false_activation_rate"],
            }
            for row in best_mean_rows
        },
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
