from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_metrics(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize visual-family smoke test runs.")
    parser.add_argument("--base-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke"))
    parser.add_argument("--manifest", default="vision_platform/ads/pilot/visual_family_smoke/dataset/manifest.csv")
    args = parser.parse_args()

    run_dirs = sorted(path for path in args.base_dir.glob("run_seed*") if (path / "summary.json").exists())
    if not run_dirs:
        raise SystemExit(f"No run_seed*/summary.json found under {args.base_dir}")

    metric_rows: list[dict[str, Any]] = []
    family_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    none_values: dict[str, list[float]] = defaultdict(list)
    for run_dir in run_dirs:
        seed = run_dir.name.replace("run_seed", "")
        summary = read_json(run_dir / "summary.json")
        for metric in read_metrics(run_dir / "test_metrics.csv"):
            row = {"seed": seed, **metric}
            metric_rows.append(row)
            family = metric["family"]
            for key in ["support", "precision", "recall", "f1", "fp", "fn"]:
                family_values[family][key].append(float(metric[key]))
        none_stats = summary.get("test_none_of_the_above", {})
        for key in ["support", "false_activation_count", "correct_abstain_count", "false_activation_rate"]:
            none_values[key].append(float(none_stats.get(key, 0)))

    write_csv(
        args.base_dir / "summary_metrics.csv",
        metric_rows,
        ["seed", "family", "support", "tp", "fp", "tn", "fn", "precision", "recall", "f1"],
    )

    lines = [
        "# Ads Visual Family Smoke Summary",
        "",
        f"Dataset: `{args.manifest}`",
        "",
        "## Per-family mean over seeds",
        "",
        "| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family in sorted(family_values):
        values = family_values[family]
        lines.append(
            "| {family} | {support:.1f} | {precision:.3f} | {recall:.3f} | {f1:.3f} | {fp:.1f} | {fn:.1f} |".format(
                family=family,
                support=mean(values["support"]),
                precision=mean(values["precision"]),
                recall=mean(values["recall"]),
                f1=mean(values["f1"]),
                fp=mean(values["fp"]),
                fn=mean(values["fn"]),
            )
        )
    lines += [
        "",
        "## None-of-the-above Check",
        "",
        f"- Support avg: {mean(none_values['support']):.1f}",
        f"- False activation count avg: {mean(none_values['false_activation_count']):.1f}",
        f"- False activation rate avg: {mean(none_values['false_activation_rate']):.3f}",
        "",
        "## Notes",
        "",
        "- Frozen MobileNetV3-small head-only smoke test, not production.",
        "- Split grouping uses content_id to prevent exact duplicate leakage.",
        "- `negative` remains a human review label, but is no longer a model head.",
        "- Negative rows are used as all-zero none-of-the-above samples.",
    ]
    (args.base_dir / "summary_report.md").write_text("\n".join(lines), encoding="utf-8")

    report = {
        "run_dirs": [str(path) for path in run_dirs],
        "families": sorted(family_values),
        "none_of_the_above": {key: mean(values) if values else 0 for key, values in none_values.items()},
        "summary_metrics": str(args.base_dir / "summary_metrics.csv"),
        "summary_report": str(args.base_dir / "summary_report.md"),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
