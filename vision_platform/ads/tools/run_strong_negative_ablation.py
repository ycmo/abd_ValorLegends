from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


SEEDS = [42, 43, 44]
WEIGHTS = [1.0, 2.0, 3.0]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_strong_negative_ids(false_activation_csv: Path, output: Path) -> set[str]:
    ids = {
        row["content_id"].strip()
        for row in read_csv(false_activation_csv)
        if row.get("content_id", "").strip()
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(sorted(ids)) + ("\n" if ids else ""), encoding="utf-8")
    return ids


def format_weight(weight: float) -> str:
    if float(weight).is_integer():
        return str(int(weight))
    return str(weight).replace(".", "_")


def run_training(args: argparse.Namespace, seed: int, weight: float, ids_file: Path, run_dir: Path) -> None:
    command = [
        sys.executable,
        str(args.train_script),
        "--manifest",
        str(args.manifest),
        "--output-dir",
        str(run_dir),
        "--seed",
        str(seed),
        "--epochs",
        str(args.epochs),
        "--batch-size",
        str(args.batch_size),
        "--device",
        args.device,
        "--strong-negative-content-ids",
        str(ids_file),
        "--strong-negative-weight",
        str(weight),
    ]
    env = os.environ.copy()
    env.setdefault("TORCH_HOME", str(args.project_root / ".cache" / "torch"))
    print("running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=args.project_root, env=env, check=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_results(output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    summary_rows: list[dict[str, Any]] = []
    family_rows: list[dict[str, Any]] = []
    none_family_rows: list[dict[str, Any]] = []
    probability_rows: list[dict[str, Any]] = []
    for run_dir in sorted(output_dir.glob("weight_*_seed*")):
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            continue
        summary = read_json(summary_path)
        weight = summary.get("strong_negative_weight", "")
        seed = run_dir.name.split("_seed")[-1]
        none = summary.get("test_none_of_the_above", {})
        summary_rows.append(
            {
                "weight": weight,
                "seed": seed,
                "none_support": none.get("support", 0),
                "none_false_activation_count": none.get("false_activation_count", 0),
                "none_false_activation_rate": none.get("false_activation_rate", 0),
                "strong_negative_train_rows": summary.get("split_counts", {}).get("train", {}).get("strong_negative_rows", 0),
                "run_dir": str(run_dir),
            }
        )
        for row in read_csv(run_dir / "test_metrics.csv"):
            family_rows.append({"weight": weight, "seed": seed, **row})
        none_family_file = run_dir / "test_none_of_the_above_family_metrics.csv"
        if none_family_file.exists():
            for row in read_csv(none_family_file):
                none_family_rows.append({"weight": weight, "seed": seed, **row})
        distribution_file = run_dir / "test_probability_distribution.csv"
        if distribution_file.exists():
            for row in read_csv(distribution_file):
                probability_rows.append({"weight": weight, "seed": seed, **row})
    return summary_rows, family_rows, none_family_rows, probability_rows


def summarize(output_dir: Path) -> None:
    summary_rows, family_rows, none_family_rows, probability_rows = collect_results(output_dir)
    write_csv(
        output_dir / "summary_by_run.csv",
        summary_rows,
        [
            "weight",
            "seed",
            "none_support",
            "none_false_activation_count",
            "none_false_activation_rate",
            "strong_negative_train_rows",
            "run_dir",
        ],
    )
    write_csv(
        output_dir / "family_metrics_by_run.csv",
        family_rows,
        ["weight", "seed", "family", "support", "tp", "fp", "tn", "fn", "precision", "recall", "f1"],
    )
    write_csv(
        output_dir / "none_family_metrics_by_run.csv",
        none_family_rows,
        ["weight", "seed", "family", "none_support", "false_activation_count", "false_activation_rate", "mean_prob_on_none", "max_prob_on_none"],
    )
    write_csv(
        output_dir / "probability_distribution_by_run.csv",
        probability_rows,
        ["weight", "seed", "family", "scope", "count", "mean", "min", "p10", "p25", "p50", "p75", "p90", "p95", "max"],
    )

    none_by_weight: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in summary_rows:
        none_by_weight[float(row["weight"])].append(row)
    family_by_weight: dict[tuple[float, str], list[dict[str, Any]]] = defaultdict(list)
    for row in family_rows:
        family_by_weight[(float(row["weight"]), row["family"])].append(row)

    baseline_recall: dict[str, float] = {}
    for (weight, family), rows in family_by_weight.items():
        if weight == 1.0:
            baseline_recall[family] = mean(float(row["recall"]) for row in rows)

    lines = [
        "# Strong Hard Negative Weight Ablation",
        "",
        "Only confirmed strong hard negatives are weighted. Labels, taxonomy, backbone, GUI, runtime, and detector are unchanged.",
        "",
        "## Split Coverage Check",
        "",
    ]
    max_train_strong = max((int(float(row["strong_negative_train_rows"])) for row in summary_rows), default=0)
    if max_train_strong == 0:
        lines += [
            "WARNING: All selected strong hard negatives are outside the training split for these runs.",
            "The sample weights therefore had no effect; identical 1x/2x/3x metrics are expected.",
            "",
        ]
    else:
        lines += [
            f"Max strong hard negative train rows: {max_train_strong}",
            "",
        ]
    lines += [
        "## None-of-the-above",
        "",
        "| weight | false activation avg | false activation worst | false activation count avg |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for weight in sorted(none_by_weight):
        rows = none_by_weight[weight]
        rates = [float(row["none_false_activation_rate"]) for row in rows]
        counts = [float(row["none_false_activation_count"]) for row in rows]
        lines.append(f"| {weight:.1f} | {mean(rates):.3f} | {max(rates):.3f} | {mean(counts):.1f} |")

    lines += [
        "",
        "## Family Metrics Mean",
        "",
        "| weight | family | precision | recall | recall loss vs 1x | f1 | fp | fn |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (weight, family), rows in sorted(family_by_weight.items()):
        precision = mean(float(row["precision"]) for row in rows)
        recall = mean(float(row["recall"]) for row in rows)
        f1 = mean(float(row["f1"]) for row in rows)
        fp = mean(float(row["fp"]) for row in rows)
        fn = mean(float(row["fn"]) for row in rows)
        recall_loss = baseline_recall.get(family, recall) - recall
        lines.append(f"| {weight:.1f} | {family} | {precision:.3f} | {recall:.3f} | {recall_loss:.3f} | {f1:.3f} | {fp:.1f} | {fn:.1f} |")

    # Negative-row family false activations.
    none_family_by_weight: dict[tuple[float, str], list[dict[str, Any]]] = defaultdict(list)
    for row in none_family_rows:
        none_family_by_weight[(float(row["weight"]), row["family"])].append(row)
    lines += [
        "",
        "## Family False Activation On None-of-the-above",
        "",
        "| weight | family | activation rate avg | activation rate worst | count avg |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for (weight, family), rows in sorted(none_family_by_weight.items()):
        rates = [float(row["false_activation_rate"]) for row in rows]
        counts = [float(row["false_activation_count"]) for row in rows]
        lines.append(f"| {weight:.1f} | {family} | {mean(rates):.3f} | {max(rates):.3f} | {mean(counts):.1f} |")

    (output_dir / "summary_report.md").write_text("\n".join(lines), encoding="utf-8")
    summary = {
        "summary_by_run": str(output_dir / "summary_by_run.csv"),
        "family_metrics_by_run": str(output_dir / "family_metrics_by_run.csv"),
        "none_family_metrics_by_run": str(output_dir / "none_family_metrics_by_run.csv"),
        "probability_distribution_by_run": str(output_dir / "probability_distribution_by_run.csv"),
        "summary_report": str(output_dir / "summary_report.md"),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run strong hard negative sample-weight ablation.")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/dataset/manifest.csv"))
    parser.add_argument("--false-activation-csv", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/none_of_the_above_review/none_of_the_above_false_activations.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/strong_negative_ablation"))
    parser.add_argument("--train-script", type=Path, default=Path("vision_platform/ads/tools/train_visual_family_smoke.py"))
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--skip-runs", action="store_true", help="Only regenerate summaries from existing run outputs.")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    args.project_root = project_root
    args.manifest = (project_root / args.manifest).resolve()
    args.false_activation_csv = (project_root / args.false_activation_csv).resolve()
    args.output_dir = (project_root / args.output_dir).resolve()
    args.train_script = (project_root / args.train_script).resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ids_file = args.output_dir / "strong_hard_negative_content_ids.txt"
    ids = write_strong_negative_ids(args.false_activation_csv, ids_file)
    print(f"strong hard negative content_ids: {len(ids)}")

    if not args.skip_runs:
        for weight in WEIGHTS:
            for seed in SEEDS:
                run_dir = args.output_dir / f"weight_{format_weight(weight)}_seed{seed}"
                run_training(args, seed, weight, ids_file, run_dir)
    summarize(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
