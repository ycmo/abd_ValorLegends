from __future__ import annotations

import argparse
import csv
import json
import math
import random
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from torchvision.models import MobileNet_V3_Small_Weights


LABEL_TO_ID = {"not_close": 0, "close": 1}
ID_TO_LABEL = {v: k for k, v in LABEL_TO_ID.items()}


@dataclass
class Row:
    image_path: Path
    label: int
    source_screen: str
    source_session: str
    ad_source: str
    icon_family: str
    reject_type: str
    candidate_score: float | None
    geometry_score: float | None
    bbox: str
    split: str


@dataclass
class ManifestRow:
    image_path: Path
    label_text: str
    review_status: str
    source_screen: str
    source_session: str
    ad_source: str
    icon_family: str
    reject_type: str
    candidate_score: float | None
    geometry_score: float | None
    bbox: str
    split: str


class CandidateDataset(Dataset):
    def __init__(self, rows: list[Row], train: bool):
        self.rows = rows
        weights = MobileNet_V3_Small_Weights.DEFAULT
        base = [
            transforms.Resize((96, 96), interpolation=transforms.InterpolationMode.BILINEAR),
            transforms.ToTensor(),
            transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std),
        ]
        if train:
            base.insert(1, transforms.ColorJitter(brightness=0.08, contrast=0.08, saturation=0.04))
        self.transform = transforms.Compose(base)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        image = Image.open(row.image_path).convert("RGB")
        return self.transform(image), row.label, idx


def parse_float(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def read_manifest_records(path: Path) -> list[ManifestRow]:
    records = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            label = (raw.get("label") or "").strip()
            review_status = (raw.get("review_status") or ("reviewed" if label else "pending")).strip()
            if label and label not in (*LABEL_TO_ID, "uncertain"):
                raise ValueError(f"unknown label: {label}")
            score_text = (raw.get("candidate_score") or "").strip()
            geometry_score_text = (raw.get("geometry_score") or score_text).strip()
            records.append(
                ManifestRow(
                    image_path=Path(raw["image_path"]),
                    label_text=label,
                    review_status=review_status,
                    source_screen=(raw.get("source_screen") or raw["image_path"]).strip(),
                    source_session=(raw.get("source_session") or "unknown_session").strip(),
                    ad_source=(raw.get("ad_source") or "unknown_ad_source").strip(),
                    icon_family=(raw.get("icon_family") or "unknown_family").strip(),
                    reject_type=(raw.get("reject_type") or "").strip(),
                    candidate_score=parse_float(score_text),
                    geometry_score=parse_float(geometry_score_text),
                    bbox=(raw.get("bbox") or "").strip(),
                    split=(raw.get("split") or "").strip().lower(),
                )
            )
    return records


def trainable_rows(records: list[ManifestRow]) -> list[Row]:
    rows = []
    for record in records:
        if record.review_status == "pending":
            continue
        if record.label_text not in LABEL_TO_ID:
            continue
        rows.append(
            Row(
                image_path=record.image_path,
                label=LABEL_TO_ID[record.label_text],
                source_screen=record.source_screen,
                source_session=record.source_session,
                ad_source=record.ad_source,
                icon_family=record.icon_family,
                reject_type=record.reject_type,
                candidate_score=record.candidate_score,
                geometry_score=record.geometry_score,
                bbox=record.bbox,
                split=record.split,
            )
        )
    return rows


def group_key(row: Row) -> str:
    return row.source_session


def session_explicit_splits(rows) -> dict[str, set[str]]:
    sessions = defaultdict(set)
    for row in rows:
        split = getattr(row, "split", "")
        if split:
            sessions[getattr(row, "source_session", "unknown_session")].add(split)
    return sessions


def validate_no_session_split(rows) -> None:
    sessions = session_explicit_splits(rows)
    conflicts = {session: sorted(splits) for session, splits in sessions.items() if len(splits) > 1}
    if conflicts:
        lines = ["source_session split leakage detected:"]
        for session, splits in sorted(conflicts.items()):
            lines.append(f"  {session}: {', '.join(splits)}")
        raise SystemExit("\n".join(lines))


def inherit_explicit_session_splits(rows: list[Row]) -> bool:
    validate_no_session_split(rows)
    session_splits = {session: next(iter(splits)) for session, splits in session_explicit_splits(rows).items()}
    if not session_splits:
        return False
    for row in rows:
        inherited = session_splits.get(row.source_session)
        if inherited and not row.split:
            row.split = inherited
    return True


def split_has_both_classes(rows: list[Row]) -> bool:
    return {row.label for row in rows} == set(LABEL_TO_ID.values())


def split_quality(splits: dict[str, list[Row]]) -> tuple[int, int]:
    target_names = ("val", "test")
    both = sum(1 for name in target_names if split_has_both_classes(splits[name]))
    non_empty = sum(1 for name in ("train", "val", "test") if splits[name])
    return both, non_empty


def assign_splits(rows: list[Row], seed: int, val_ratio: float, test_ratio: float) -> dict[str, list[Row]]:
    if inherit_explicit_session_splits(rows):
        splits = {"train": [], "val": [], "test": []}
        blank_grouped = defaultdict(list)
        for row in rows:
            if row.split:
                splits[row.split].append(row)
            else:
                blank_grouped[group_key(row)].append(row)
        blank_groups = list(blank_grouped)
        rng = random.Random(seed)
        rng.shuffle(blank_groups)
        n = len(blank_groups)
        n_test = max(1, round(n * test_ratio)) if n >= 3 and not splits["test"] else 0
        n_val = max(1, round(n * val_ratio)) if n - n_test >= 2 and not splits["val"] else 0
        test_groups = set(blank_groups[:n_test])
        val_groups = set(blank_groups[n_test : n_test + n_val])
        for key, items in blank_grouped.items():
            if key in test_groups:
                split = "test"
            elif key in val_groups:
                split = "val"
            else:
                split = "train"
            for row in items:
                row.split = split
                splits[split].append(row)
        validate_no_session_split(rows)
        for name in ("val", "test"):
            if splits[name] and not split_has_both_classes(splits[name]):
                warnings.warn(f"{name} split does not contain both close and not_close labels", RuntimeWarning)
        return splits

    grouped = defaultdict(list)
    for row in rows:
        grouped[group_key(row)].append(row)
    groups = list(grouped)
    best_splits = None
    best_quality = (-1, -1)
    for attempt in range(64):
        rng = random.Random(seed + attempt)
        shuffled = groups[:]
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_test = max(1, round(n * test_ratio)) if n >= 3 else 0
        n_val = max(1, round(n * val_ratio)) if n - n_test >= 2 else 0
        test_groups = set(shuffled[:n_test])
        val_groups = set(shuffled[n_test : n_test + n_val])
        splits = {"train": [], "val": [], "test": []}
        for key, items in grouped.items():
            if key in test_groups:
                split = "test"
            elif key in val_groups:
                split = "val"
            else:
                split = "train"
            for row in items:
                row.split = split
                splits[split].append(row)
        quality = split_quality(splits)
        if quality > best_quality:
            best_quality = quality
            best_splits = splits
        if quality[0] == 2 and quality[1] == 3:
            break
    assert best_splits is not None
    validate_no_session_split([row for split_rows in best_splits.values() for row in split_rows])
    for name in ("val", "test"):
        if best_splits[name] and not split_has_both_classes(best_splits[name]):
            warnings.warn(f"{name} split does not contain both close and not_close labels", RuntimeWarning)
    return best_splits


def build_model(device: torch.device):
    weights = MobileNet_V3_Small_Weights.DEFAULT
    model = models.mobilenet_v3_small(weights=weights)
    for param in model.features.parameters():
        param.requires_grad = False
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, 2)
    return model.to(device)


def class_weights(rows: list[Row], device: torch.device):
    counts = Counter(row.label for row in rows)
    total = sum(counts.values())
    weights = [total / max(counts.get(i, 1), 1) for i in range(2)]
    return torch.tensor(weights, dtype=torch.float32, device=device)


def make_loader(rows: list[Row], batch_size: int, train: bool):
    dataset = CandidateDataset(rows, train=train)
    return DataLoader(dataset, batch_size=batch_size, shuffle=train, num_workers=0)


@torch.no_grad()
def predict(model, rows: list[Row], batch_size: int, device: torch.device):
    loader = make_loader(rows, batch_size=batch_size, train=False)
    model.eval()
    y_true, y_prob, row_indices = [], [], []
    for images, labels, indices in loader:
        images = images.to(device)
        logits = model(images)
        probs = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
        y_true.extend(labels.numpy().tolist())
        y_prob.extend(probs.tolist())
        row_indices.extend(indices.numpy().tolist())
    return np.array(y_true), np.array(y_prob), row_indices


def confusion_at_threshold(y_true, y_prob, threshold: float):
    y_pred = (y_prob >= threshold).astype(np.int64)
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def binary_metrics(y_true, y_prob, threshold: float):
    c = confusion_at_threshold(y_true, y_prob, threshold)
    precision = c["tp"] / max(c["tp"] + c["fp"], 1)
    recall = c["tp"] / max(c["tp"] + c["fn"], 1)
    fpr = c["fp"] / max(c["fp"] + c["tn"], 1)
    return {**c, "precision": precision, "recall": recall, "fpr": fpr}


def curve_points(y_true, y_prob):
    thresholds = sorted(set([0.0, 1.0, *y_prob.tolist()]), reverse=True)
    pr, roc = [], []
    positives = max(int((y_true == 1).sum()), 1)
    negatives = max(int((y_true == 0).sum()), 1)
    for threshold in thresholds:
        c = confusion_at_threshold(y_true, y_prob, threshold)
        precision = c["tp"] / max(c["tp"] + c["fp"], 1)
        recall = c["tp"] / positives
        fpr = c["fp"] / negatives
        tpr = recall
        pr.append((recall, precision))
        roc.append((fpr, tpr))
    return pr, roc


def draw_curve(points, output: Path, title: str, x_label: str, y_label: str):
    width, height = 720, 480
    margin = 56
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([margin, margin, width - margin, height - margin], outline=(30, 30, 30))
    draw.text((margin, 18), title, fill=(20, 20, 20))
    draw.text((width // 2 - 30, height - 34), x_label, fill=(20, 20, 20))
    draw.text((8, height // 2), y_label, fill=(20, 20, 20))
    if points:
        mapped = []
        for x, y in points:
            px = margin + x * (width - 2 * margin)
            py = height - margin - y * (height - 2 * margin)
            mapped.append((px, py))
        if len(mapped) == 1:
            x, y = mapped[0]
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(0, 90, 200))
        else:
            draw.line(mapped, fill=(0, 90, 200), width=3)
    image.save(output)


def draw_confusion(confusion: dict[str, int], output: Path, threshold: float):
    image = Image.new("RGB", (480, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 18), f"Confusion matrix @ threshold {threshold:.3f}", fill=(20, 20, 20))
    cells = [("TN", confusion["tn"]), ("FP", confusion["fp"]), ("FN", confusion["fn"]), ("TP", confusion["tp"])]
    positions = [(90, 90), (250, 90), (90, 210), (250, 210)]
    for (label, value), (x, y) in zip(cells, positions):
        draw.rectangle([x, y, x + 120, y + 80], outline=(30, 30, 30), width=2)
        draw.text((x + 14, y + 18), label, fill=(20, 20, 20))
        draw.text((x + 14, y + 44), str(value), fill=(20, 20, 20))
    image.save(output)


def contact_sheet(rows: list[Row], y_true, y_prob, row_indices, output: Path, false_positive: bool, threshold: float):
    chosen = []
    for true, prob, idx in zip(y_true, y_prob, row_indices):
        pred = prob >= threshold
        if false_positive and true == 0 and pred:
            chosen.append((prob, rows[idx]))
        elif not false_positive and true == 1 and not pred:
            chosen.append((prob, rows[idx]))
    chosen.sort(key=lambda item: item[0], reverse=false_positive)
    chosen = chosen[:80]
    cols, thumb_w, thumb_h, pad, label_h = 5, 128, 96, 12, 30
    rows_n = max(1, math.ceil(len(chosen) / cols))
    image = Image.new("RGB", (cols * (thumb_w + pad) + pad, rows_n * (thumb_h + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for i, (prob, row) in enumerate(chosen):
        x = pad + (i % cols) * (thumb_w + pad)
        y = pad + (i // cols) * (thumb_h + label_h + pad)
        try:
            im = Image.open(row.image_path).convert("RGB")
        except Exception:
            continue
        scale = min(thumb_w / im.width, thumb_h / im.height)
        resized = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
        ox = x + (thumb_w - resized.width) // 2
        oy = y + (thumb_h - resized.height) // 2
        image.paste(resized, (ox, oy))
        draw.rectangle([x, y, x + thumb_w - 1, y + thumb_h - 1], outline=(200, 40, 40), width=2)
        draw.text((x, y + thumb_h + 4), f"p={prob:.3f}", fill=(20, 20, 20))
    image.save(output)


def save_predictions(rows: list[Row], y_true, y_prob, row_indices, output: Path):
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image_path",
                "label",
                "p_close",
                "source_session",
                "source_screen",
                "ad_source",
                "icon_family",
                "reject_type",
                "candidate_score",
                "geometry_score",
                "bbox",
            ],
        )
        writer.writeheader()
        for true, prob, idx in zip(y_true, y_prob, row_indices):
            row = rows[idx]
            writer.writerow(
                {
                    "image_path": str(row.image_path),
                    "label": ID_TO_LABEL[int(true)],
                    "p_close": f"{prob:.6f}",
                    "source_session": row.source_session,
                    "source_screen": row.source_screen,
                    "ad_source": row.ad_source,
                    "icon_family": row.icon_family,
                    "reject_type": row.reject_type,
                    "candidate_score": "" if row.candidate_score is None else row.candidate_score,
                    "geometry_score": "" if row.geometry_score is None else row.geometry_score,
                    "bbox": row.bbox,
                }
            )


def write_group_metrics(rows: list[Row], y_true, y_prob, row_indices, output: Path, group_attr: str, threshold: float):
    grouped = defaultdict(list)
    for true, prob, idx in zip(y_true, y_prob, row_indices):
        grouped[getattr(rows[idx], group_attr)].append((true, prob))
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["group", "count", "positives", "negatives", "tp", "fp", "tn", "fn", "precision", "recall", "fpr"],
        )
        writer.writeheader()
        for group, items in sorted(grouped.items()):
            gy_true = np.array([item[0] for item in items])
            gy_prob = np.array([item[1] for item in items])
            metrics = binary_metrics(gy_true, gy_prob, threshold)
            writer.writerow(
                {
                    "group": group,
                    "count": len(items),
                    "positives": int((gy_true == 1).sum()),
                    "negatives": int((gy_true == 0).sum()),
                    **metrics,
                }
            )


def complete_screen_sets(records: list[ManifestRow], eval_split: str) -> tuple[set[str], dict[str, int]]:
    screens = defaultdict(list)
    for record in records:
        if record.split == eval_split:
            screens[record.source_screen].append(record)
    complete = set()
    for source_screen, items in screens.items():
        if items and all(item.review_status != "pending" and item.label_text in LABEL_TO_ID for item in items):
            complete.add(source_screen)
    stats = {
        "total_screens": len(screens),
        "complete_screens": len(complete),
        "excluded_incomplete_screens": len(screens) - len(complete),
    }
    return complete, stats


def write_per_screen_top1(
    rows: list[Row],
    y_true,
    y_prob,
    row_indices,
    output: Path,
    records: list[ManifestRow],
    eval_split: str,
    threshold: float,
) -> dict[str, int]:
    complete_screens, stats = complete_screen_sets(records, eval_split)
    screens = defaultdict(list)
    for true, prob, idx in zip(y_true, y_prob, row_indices):
        row = rows[idx]
        if row.source_screen in complete_screens:
            screens[row.source_screen].append((float(prob), int(true), row))
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source_screen",
                "source_session",
                "candidate_count",
                "has_close",
                "top1_true_label",
                "top1_p_close",
                "top1_predicted_close",
                "would_click",
                "top1_correct_for_positive_screen",
                "positive_screen_miss_or_abstain",
                "correct_abstain_on_negative_screen",
                "false_click_on_negative_screen",
                "top1_image_path",
                "top1_bbox",
                "top1_geometry_score",
            ],
        )
        writer.writeheader()
        for source_screen, items in sorted(screens.items()):
            items.sort(key=lambda item: item[0], reverse=True)
            top_prob, top_label, top_row = items[0]
            has_close = any(label == 1 for _prob, label, _row in items)
            would_click = top_prob >= threshold
            success_positive = has_close and top_label == 1 and would_click
            false_click_negative = (not has_close) and would_click
            writer.writerow(
                {
                    "source_screen": source_screen,
                    "source_session": top_row.source_session,
                    "candidate_count": len(items),
                    "has_close": int(has_close),
                    "top1_true_label": ID_TO_LABEL[top_label],
                    "top1_p_close": f"{top_prob:.6f}",
                    "top1_predicted_close": int(would_click),
                    "would_click": int(would_click),
                    "top1_correct_for_positive_screen": int(success_positive),
                    "positive_screen_miss_or_abstain": int(has_close and not success_positive),
                    "correct_abstain_on_negative_screen": int((not has_close) and not would_click),
                    "false_click_on_negative_screen": int(false_click_negative),
                    "top1_image_path": str(top_row.image_path),
                    "top1_bbox": top_row.bbox,
                    "top1_geometry_score": "" if top_row.geometry_score is None else top_row.geometry_score,
                }
            )
    return stats


def train(args):
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    args.torch_cache_dir.mkdir(parents=True, exist_ok=True)
    torch.hub.set_dir(str(args.torch_cache_dir))
    records = read_manifest_records(args.manifest)
    validate_no_session_split(records)
    rows = trainable_rows(records)
    splits = assign_splits(rows, args.seed, args.val_ratio, args.test_ratio)
    if not splits["train"] or not splits["val"]:
        raise SystemExit("need non-empty train and val splits; add a split column or more group diversity")
    session_to_split = {}
    for split, split_rows in splits.items():
        for row in split_rows:
            session_to_split[row.source_session] = split
    for record in records:
        if not record.split and record.source_session in session_to_split:
            record.split = session_to_split[record.source_session]
    validate_no_session_split(records)

    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else args.device)
    model = build_model(device)
    train_loader = make_loader(splits["train"], args.batch_size, train=True)
    criterion = nn.CrossEntropyLoss(weight=class_weights(splits["train"], device))
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=args.lr, weight_decay=args.weight_decay)

    best_val_loss = float("inf")
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        seen = 0
        for images, labels, _indices in train_loader:
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * labels.size(0)
            seen += labels.size(0)

        y_true, y_prob, _ = predict(model, splits["val"], args.batch_size, device)
        eps = 1e-7
        val_loss = -np.mean(y_true * np.log(y_prob + eps) + (1 - y_true) * np.log(1 - y_prob + eps))
        conf = confusion_at_threshold(y_true, y_prob, args.threshold)
        history.append({"epoch": epoch, "train_loss": total_loss / max(seen, 1), "val_loss": float(val_loss), **conf})
        print(f"epoch={epoch} train_loss={history[-1]['train_loss']:.4f} val_loss={val_loss:.4f} conf={conf}")
        if val_loss < best_val_loss:
            best_val_loss = float(val_loss)
            torch.save({"model": model.state_dict(), "args": vars(args)}, output_dir / "best.pt")

    checkpoint = torch.load(output_dir / "best.pt", map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    eval_split = "test" if splits["test"] else "val"
    eval_rows = splits[eval_split]
    y_true, y_prob, row_indices = predict(model, eval_rows, args.batch_size, device)
    confusion = confusion_at_threshold(y_true, y_prob, args.threshold)
    pr, roc = curve_points(y_true, y_prob)

    save_predictions(eval_rows, y_true, y_prob, row_indices, output_dir / "predictions.csv")
    write_group_metrics(eval_rows, y_true, y_prob, row_indices, output_dir / "per_session_metrics.csv", "source_session", args.threshold)
    per_screen_stats = write_per_screen_top1(
        eval_rows,
        y_true,
        y_prob,
        row_indices,
        output_dir / "per_screen_top1.csv",
        records,
        eval_split,
        args.threshold,
    )
    draw_confusion(confusion, output_dir / "confusion_matrix.png", args.threshold)
    draw_curve(pr, output_dir / "pr_curve.png", "PR curve", "Recall", "Precision")
    draw_curve(roc, output_dir / "roc_curve.png", "ROC curve", "FPR", "TPR")
    contact_sheet(eval_rows, y_true, y_prob, row_indices, output_dir / "false_positive_contact_sheet.png", True, args.threshold)
    contact_sheet(eval_rows, y_true, y_prob, row_indices, output_dir / "false_negative_contact_sheet.png", False, args.threshold)

    metrics = {
        "eval_split": eval_split,
        "splits": {key: len(value) for key, value in splits.items()},
        "threshold": args.threshold,
        "confusion": confusion,
        "per_screen": per_screen_stats,
        "history": history,
        "note": "Tiny datasets are smoke tests only; use group-held-out data before trusting deployment.",
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"wrote outputs: {output_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--torch-cache-dir", type=Path, default=Path("close_x_classifier/.torch_cache"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    train(args)


if __name__ == "__main__":
    main()
