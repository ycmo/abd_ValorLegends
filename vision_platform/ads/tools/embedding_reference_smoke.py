from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from torchvision.models import MobileNet_V3_Small_Weights


DEFAULT_FAMILIES = ["next", "google_play"]
ALL_FAMILIES = [
    "x_mark",
    "play_triangle",
    "google_play",
    "next",
    "free",
    "got",
    "arrow",
]


@dataclass
class Row:
    index: int
    image_path: Path
    families: str
    labels: dict[str, int]
    instance_id: str
    content_id: str
    original_path: str
    relative_path: str
    source_root: str


class ImageDataset(Dataset):
    def __init__(self, rows: list[Row]):
        self.rows = rows
        weights = MobileNet_V3_Small_Weights.DEFAULT
        self.transform = transforms.Compose(
            [
                transforms.Resize((96, 96), interpolation=transforms.InterpolationMode.BILINEAR),
                transforms.ToTensor(),
                transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std),
            ]
        )

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        image = Image.open(self.rows[index].image_path).convert("RGB")
        return self.transform(image), index


def read_manifest(path: Path) -> list[Row]:
    rows: list[Row] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for index, raw in enumerate(csv.DictReader(handle)):
            labels = {family: int(float(raw.get(f"label_{family}") or 0)) for family in ALL_FAMILIES}
            rows.append(
                Row(
                    index=index,
                    image_path=Path(raw["image_path"]),
                    families=raw.get("families", ""),
                    labels=labels,
                    instance_id=raw.get("instance_id", ""),
                    content_id=raw.get("content_id", ""),
                    original_path=raw.get("original_path", ""),
                    relative_path=raw.get("relative_path", ""),
                    source_root=raw.get("source_root", ""),
                )
            )
    return rows


def build_embedder(device: torch.device) -> torch.nn.Module:
    weights = MobileNet_V3_Small_Weights.DEFAULT
    model = models.mobilenet_v3_small(weights=weights)
    embedder = torch.nn.Sequential(model.features, model.avgpool, torch.nn.Flatten())
    embedder.eval()
    embedder.to(device)
    return embedder


@torch.inference_mode()
def embed_rows_mobilenet(rows: list[Row], device: torch.device, batch_size: int) -> np.ndarray:
    dataset = ImageDataset(rows)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    embedder = build_embedder(device)
    features = np.zeros((len(rows), 576), dtype=np.float32)
    for images, indices in loader:
        embeddings = embedder(images.to(device)).detach().cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.maximum(norms, 1e-9)
        features[indices.numpy()] = embeddings
    return features


def embed_rows_rgb(rows: list[Row]) -> np.ndarray:
    features = np.zeros((len(rows), 96 * 96 * 3), dtype=np.float32)
    for row in rows:
        image = Image.open(row.image_path).convert("RGB").resize((96, 96), Image.Resampling.BILINEAR)
        vector = np.asarray(image, dtype=np.float32).reshape(-1) / 255.0
        vector = vector - float(vector.mean())
        vector = vector / max(float(np.linalg.norm(vector)), 1e-9)
        features[row.index] = vector
    return features


def score_family(rows: list[Row], features: np.ndarray, family: str) -> list[dict[str, Any]]:
    reference_indices = [row.index for row in rows if row.labels.get(family, 0) == 1]
    if not reference_indices:
        return []
    reference_features = features[reference_indices]
    reference_rows = [rows[index] for index in reference_indices]
    scores: list[dict[str, Any]] = []
    for row in rows:
        usable = [
            (ref_pos, ref_row)
            for ref_pos, ref_row in enumerate(reference_rows)
            if not row.content_id or ref_row.content_id != row.content_id
        ]
        if not usable:
            score = float("nan")
            best_ref = ""
            best_ref_content = ""
        else:
            usable_positions = [item[0] for item in usable]
            sims = reference_features[usable_positions] @ features[row.index]
            best_local = int(np.argmax(sims))
            best_ref_row = usable[best_local][1]
            score = float(sims[best_local])
            best_ref = best_ref_row.instance_id
            best_ref_content = best_ref_row.content_id
        scores.append(
            {
                "family": family,
                "score": score,
                "true_label": row.labels.get(family, 0),
                "families": row.families,
                "instance_id": row.instance_id,
                "content_id": row.content_id,
                "image_path": str(row.image_path),
                "original_path": row.original_path,
                "relative_path": row.relative_path,
                "source_root": row.source_root,
                "best_reference_instance_id": best_ref,
                "best_reference_content_id": best_ref_content,
            }
        )
    return scores


def metric_for(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    valid = [row for row in rows if not math.isnan(float(row["score"]))]
    tp = fp = tn = fn = 0
    for row in valid:
        true = int(row["true_label"])
        pred = int(float(row["score"]) >= threshold)
        if true and pred:
            tp += 1
        elif true and not pred:
            fn += 1
        elif not true and pred:
            fp += 1
        else:
            tn += 1
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    return {
        "threshold": threshold,
        "support": tp + fn,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_contact_sheet(rows: list[dict[str, Any]], output: Path, title: str, max_items: int = 80) -> None:
    items = rows[:max_items]
    cols, thumb, label_h, pad = 8, 96, 54, 8
    count_rows = max(1, math.ceil(len(items) / cols))
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, count_rows * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((pad, 2), title[:120], fill=(20, 20, 20), font=font)
    for pos, row in enumerate(items):
        x = pad + (pos % cols) * (thumb + pad)
        y = pad + (pos // cols) * (thumb + label_h + pad) + pad
        try:
            image = Image.open(row["image_path"]).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        except Exception:
            image = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(image, (x, y))
        score = float(row["score"])
        draw.text((x, y + thumb + 2), f"{row['family']} s={score:.3f}", fill=(130, 20, 20), font=font)
        draw.text((x, y + thumb + 18), str(row["families"])[:22], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 34), str(row["instance_id"])[:22], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prototype visual-family scoring with frozen MobileNet embeddings.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--families", nargs="+", default=DEFAULT_FAMILIES)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--backend", choices=["mobilenet", "rgb"], default="mobilenet")
    parser.add_argument("--threshold-start", type=float, default=0.50)
    parser.add_argument("--threshold-stop", type=float, default=0.98)
    parser.add_argument("--threshold-step", type=float, default=0.02)
    args = parser.parse_args()

    rows = read_manifest(args.manifest)
    device = torch.device(args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.backend == "mobilenet":
        features = embed_rows_mobilenet(rows, device, args.batch_size)
    else:
        features = embed_rows_rgb(rows)
    score_rows: list[dict[str, Any]] = []
    threshold_rows: list[dict[str, Any]] = []
    best_rows: list[dict[str, Any]] = []

    thresholds: list[float] = []
    value = args.threshold_start
    while value <= args.threshold_stop + 1e-9:
        thresholds.append(round(value, 4))
        value += args.threshold_step

    for family in args.families:
        family_scores = score_family(rows, features, family)
        score_rows.extend(family_scores)
        for threshold in thresholds:
            row = {"family": family, **metric_for(family_scores, threshold)}
            threshold_rows.append(row)
        family_thresholds = [row for row in threshold_rows if row["family"] == family]
        best = max(family_thresholds, key=lambda row: (row["f1"], row["recall"], row["precision"], row["threshold"]))
        best_rows.append(best)

        positives = sorted(
            [row for row in family_scores if int(row["true_label"]) == 1 and not math.isnan(float(row["score"]))],
            key=lambda row: float(row["score"]),
        )
        hard_false_matches = sorted(
            [row for row in family_scores if int(row["true_label"]) == 0 and not math.isnan(float(row["score"]))],
            key=lambda row: float(row["score"]),
            reverse=True,
        )
        write_contact_sheet(positives, args.output_dir / f"{family}_positive_low_similarity.png", f"{family} positives, lowest similarity")
        write_contact_sheet(hard_false_matches, args.output_dir / f"{family}_negative_high_similarity.png", f"{family} negatives, highest similarity")

    score_fields = [
        "family",
        "score",
        "true_label",
        "families",
        "instance_id",
        "content_id",
        "image_path",
        "original_path",
        "relative_path",
        "source_root",
        "best_reference_instance_id",
        "best_reference_content_id",
    ]
    metric_fields = ["family", "threshold", "support", "tp", "fp", "tn", "fn", "precision", "recall", "f1"]
    write_csv(args.output_dir / "embedding_reference_scores.csv", score_rows, score_fields)
    write_csv(args.output_dir / "threshold_sweep.csv", threshold_rows, metric_fields)
    write_csv(args.output_dir / "best_thresholds.csv", best_rows, metric_fields)

    summary = {
        "manifest": str(args.manifest),
        "rows": len(rows),
        "families": args.families,
        "device": str(device),
        "backend": args.backend,
        "reference_counts": {
            family: sum(1 for row in rows if row.labels.get(family, 0) == 1)
            for family in args.families
        },
        "best_thresholds": best_rows,
        "outputs": {
            "scores": str(args.output_dir / "embedding_reference_scores.csv"),
            "threshold_sweep": str(args.output_dir / "threshold_sweep.csv"),
            "best_thresholds": str(args.output_dir / "best_thresholds.csv"),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Embedding Reference Smoke Test",
        "",
        f"Manifest: `{args.manifest}`",
        f"Rows: `{len(rows)}`",
        f"Device: `{device}`",
        "",
        "| family | references | threshold | precision | recall | f1 | fp | fn |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in best_rows:
        lines.append(
            f"| {row['family']} | {summary['reference_counts'][row['family']]} | {row['threshold']:.2f} | "
            f"{row['precision']:.3f} | {row['recall']:.3f} | {row['f1']:.3f} | {row['fp']} | {row['fn']} |"
        )
    (args.output_dir / "summary_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
