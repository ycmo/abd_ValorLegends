from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch import nn

os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parent / ".torch_cache"))

from train import (
    ID_TO_LABEL,
    binary_metrics,
    build_model,
    class_weights,
    contact_sheet,
    make_loader,
    predict,
    read_manifest_records,
    save_predictions,
    trainable_rows,
)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def train(args) -> None:
    set_seed(args.seed)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    records = read_manifest_records(args.manifest)
    rows = trainable_rows(records)
    counts = Counter(row.label for row in rows)
    if set(counts) != {0, 1}:
        raise SystemExit(f"deployment training needs both classes; counts={dict(counts)}")

    device = torch.device(args.device)
    model = build_model(device)
    loader = make_loader(rows, args.batch_size, train=True)
    criterion = nn.CrossEntropyLoss(weight=class_weights(rows, device))
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=args.lr, weight_decay=1e-4)

    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        seen = 0
        for images, labels, _indices in loader:
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            batch = int(labels.numel())
            total_loss += float(loss.item()) * batch
            seen += batch
        train_loss = total_loss / max(seen, 1)
        history.append({"epoch": epoch, "train_loss": train_loss})
        print(f"epoch={epoch} train_loss={train_loss:.4f}")

    checkpoint = {
        "model": model.state_dict(),
        "args": vars(args),
        "class_counts": {ID_TO_LABEL[key]: value for key, value in sorted(counts.items())},
        "note": "Deployment checkpoint trained on all labeled Stage 0.6 object-crop rows. Do not use as a validation result.",
    }
    torch.save(checkpoint, output_dir / "best.pt")

    y_true, y_prob, row_indices = predict(model, rows, args.batch_size, device)
    metrics = binary_metrics(y_true, y_prob, args.threshold)
    save_predictions(rows, y_true, y_prob, row_indices, output_dir / "train_predictions.csv")
    contact_sheet(rows, y_true, y_prob, row_indices, output_dir / "train_false_positive_contact_sheet.png", True, args.threshold)
    contact_sheet(rows, y_true, y_prob, row_indices, output_dir / "train_false_negative_contact_sheet.png", False, args.threshold)

    with (output_dir / "metrics.json").open("w", encoding="utf-8") as f:
        json.dump(
            {
                "manifest": str(args.manifest),
                "rows": len(rows),
                "class_counts": {ID_TO_LABEL[key]: value for key, value in sorted(counts.items())},
                "threshold": args.threshold,
                "train_metrics": metrics,
                "history": history,
                "note": "Training-set metrics only; this is a deployment checkpoint, not a generalization benchmark.",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with (output_dir / "deployment_manifest_summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["label", "count"])
        writer.writeheader()
        for label_id, count in sorted(counts.items()):
            writer.writerow({"label": ID_TO_LABEL[label_id], "count": count})

    print(f"wrote: {output_dir / 'best.pt'}")
    print(f"counts: {dict((ID_TO_LABEL[k], v) for k, v in sorted(counts.items()))}")
    print(f"train_metrics: {metrics}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("close_x_classifier/data/stage0_6_canonical_object_poc/manifest.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("close_x_classifier/runs/stage0_6_deployment"))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
