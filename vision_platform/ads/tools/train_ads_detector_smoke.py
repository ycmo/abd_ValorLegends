from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_320_fpn
from torchvision.ops import box_iou


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def collate(batch):
    return tuple(zip(*batch))


def parse_box(row: dict[str, str]) -> list[float]:
    x = float(row["bbox_x"])
    y = float(row["bbox_y"])
    w = float(row["bbox_w"])
    h = float(row["bbox_h"])
    return [x, y, x + w, y + h]


class AdsDetectorDataset(Dataset):
    def __init__(self, screen_rows: list[dict[str, str]], boxes_by_screen: dict[str, list[list[float]]]):
        self.screen_rows = screen_rows
        self.boxes_by_screen = boxes_by_screen
        self.to_tensor = transforms.ToTensor()

    def __len__(self) -> int:
        return len(self.screen_rows)

    def __getitem__(self, index: int):
        row = self.screen_rows[index]
        image = Image.open(row["image_path"]).convert("RGB")
        boxes = torch.tensor(self.boxes_by_screen.get(row["screen_id"], []), dtype=torch.float32)
        if boxes.numel() == 0:
            boxes = boxes.reshape(0, 4)
        labels = torch.ones((boxes.shape[0],), dtype=torch.int64)
        target = {
            "boxes": boxes,
            "labels": labels,
            "image_id": torch.tensor([index], dtype=torch.int64),
            "area": (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]) if boxes.numel() else torch.zeros((0,), dtype=torch.float32),
            "iscrowd": torch.zeros((boxes.shape[0],), dtype=torch.int64),
        }
        return self.to_tensor(image), target, row


def make_model(num_classes: int = 2):
    try:
        return fasterrcnn_mobilenet_v3_large_320_fpn(
            weights=None,
            weights_backbone=None,
            num_classes=num_classes,
            min_size=320,
            max_size=640,
        )
    except TypeError:
        return fasterrcnn_mobilenet_v3_large_320_fpn(
            pretrained=False,
            pretrained_backbone=False,
            num_classes=num_classes,
            min_size=320,
            max_size=640,
        )


def assign_splits(rows: list[dict[str, str]], seed: int, val_ratio: float, test_ratio: float) -> dict[str, list[dict[str, str]]]:
    explicit: dict[str, str] = {}
    valid = {"train", "val", "test"}
    groups = sorted({row.get("split_group") or row["screen_id"] for row in rows})
    group_to_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        group = row.get("split_group") or row["screen_id"]
        group_to_rows[group].append(row)
        split = (row.get("split") or "").lower()
        if split:
            if split not in valid:
                raise SystemExit(f"invalid split={split} for group={group}")
            if group in explicit and explicit[group] != split:
                raise SystemExit(f"conflicting explicit split for group={group}: {explicit[group]} vs {split}")
            explicit[group] = split

    auto_groups = [group for group in groups if group not in explicit]
    rng = random.Random(seed)
    rng.shuffle(auto_groups)
    n = len(auto_groups)
    n_test = max(1, round(n * test_ratio)) if n >= 3 else 0
    n_val = max(1, round(n * val_ratio)) if n >= 3 else 0
    split_by_group = dict(explicit)
    for group in auto_groups[:n_test]:
        split_by_group[group] = "test"
    for group in auto_groups[n_test : n_test + n_val]:
        split_by_group[group] = "val"
    for group in auto_groups[n_test + n_val :]:
        split_by_group[group] = "train"

    splits = {"train": [], "val": [], "test": []}
    for row in rows:
        split = split_by_group[row.get("split_group") or row["screen_id"]]
        row["split"] = split
        splits[split].append(row)
    return splits


def limit_rows(rows: list[dict[str, str]], max_screens: int) -> list[dict[str, str]]:
    if max_screens <= 0 or len(rows) <= max_screens:
        return rows
    positives = [row for row in rows if int(float(row.get("positive_bbox_count") or 0)) > 0]
    negatives = [row for row in rows if int(float(row.get("positive_bbox_count") or 0)) == 0]
    keep_pos = min(len(positives), max_screens)
    keep_neg = min(len(negatives), max(0, max_screens - keep_pos))
    return positives[:keep_pos] + negatives[:keep_neg]


@torch.inference_mode()
def evaluate(model, rows: list[dict[str, str]], boxes_by_screen: dict[str, list[list[float]]], device, score_threshold: float, iou_threshold: float, output_dir: Path) -> dict[str, Any]:
    dataset = AdsDetectorDataset(rows, boxes_by_screen)
    loader = DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=collate)
    model.eval()
    eval_rows: list[dict[str, Any]] = []
    covered_gt = total_gt = positive_screens = positive_hit_screens = 0
    negative_screens = negative_false_positive_screens = 0
    overlay_items = []
    for images, _targets, raw_rows in loader:
        image = images[0].to(device)
        row = raw_rows[0]
        prediction = model([image])[0]
        pred_boxes = prediction["boxes"].detach().cpu()
        pred_scores = prediction["scores"].detach().cpu()
        keep = pred_scores >= score_threshold
        pred_boxes = pred_boxes[keep]
        pred_scores = pred_scores[keep]
        gt_boxes = torch.tensor(boxes_by_screen.get(row["screen_id"], []), dtype=torch.float32)
        has_gt = gt_boxes.numel() > 0
        hit_screen = False
        gt_hit_count = 0
        if has_gt:
            positive_screens += 1
            total_gt += gt_boxes.shape[0]
            if len(pred_boxes):
                ious = box_iou(gt_boxes, pred_boxes)
                gt_hits = (ious.max(dim=1).values >= iou_threshold)
                gt_hit_count = int(gt_hits.sum().item())
                covered_gt += gt_hit_count
                hit_screen = gt_hit_count > 0
            if hit_screen:
                positive_hit_screens += 1
        else:
            negative_screens += 1
            if len(pred_boxes):
                negative_false_positive_screens += 1

        eval_rows.append(
            {
                "screen_id": row["screen_id"],
                "split": row.get("split", ""),
                "has_gt": int(has_gt),
                "gt_count": int(gt_boxes.shape[0]) if has_gt else 0,
                "pred_count": int(len(pred_boxes)),
                "max_score": round(float(pred_scores.max().item()), 5) if len(pred_scores) else 0.0,
                "gt_hit_count": gt_hit_count,
                "hit_screen": int(hit_screen),
                "image_path": row["image_path"],
            }
        )
        if len(overlay_items) < 80 and (not has_gt or not hit_screen or len(pred_boxes)):
            overlay_items.append((row, gt_boxes, pred_boxes[:5], pred_scores[:5]))

    write_csv(
        output_dir / "eval_predictions.csv",
        eval_rows,
        ["screen_id", "split", "has_gt", "gt_count", "pred_count", "max_score", "gt_hit_count", "hit_screen", "image_path"],
    )
    write_overlay_sheet(overlay_items, output_dir / "eval_overlay_sheet.png")
    return {
        "score_threshold": score_threshold,
        "iou_threshold": iou_threshold,
        "positive_screens": positive_screens,
        "positive_hit_screens": positive_hit_screens,
        "positive_screen_recall": round(positive_hit_screens / max(positive_screens, 1), 4),
        "gt_boxes": total_gt,
        "gt_boxes_covered": covered_gt,
        "gt_box_recall": round(covered_gt / max(total_gt, 1), 4),
        "negative_screens": negative_screens,
        "negative_false_positive_screens": negative_false_positive_screens,
        "negative_fp_screen_rate": round(negative_false_positive_screens / max(negative_screens, 1), 4),
    }


def write_overlay_sheet(items, output: Path) -> None:
    if not items:
        return
    cols, thumb_w, thumb_h, label_h, pad = 4, 240, 135, 28, 8
    rows_n = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (thumb_w + pad) + pad, rows_n * (thumb_h + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for pos, (row, gt_boxes, pred_boxes, pred_scores) in enumerate(items):
        x = pad + (pos % cols) * (thumb_w + pad)
        y = pad + (pos // cols) * (thumb_h + label_h + pad)
        image = Image.open(row["image_path"]).convert("RGB")
        sx = thumb_w / image.width
        sy = thumb_h / image.height
        image = image.resize((thumb_w, thumb_h), Image.Resampling.BILINEAR)
        item_draw = ImageDraw.Draw(image)
        for box in gt_boxes:
            x1, y1, x2, y2 = [float(v) for v in box]
            item_draw.rectangle((x1 * sx, y1 * sy, x2 * sx, y2 * sy), outline=(0, 220, 0), width=2)
        for box, score in zip(pred_boxes, pred_scores):
            x1, y1, x2, y2 = [float(v) for v in box]
            item_draw.rectangle((x1 * sx, y1 * sy, x2 * sx, y2 * sy), outline=(240, 40, 40), width=2)
            item_draw.text((x1 * sx, max(0, y1 * sy - 10)), f"{float(score):.2f}", fill=(240, 40, 40), font=font)
        sheet.paste(image, (x, y))
        draw.text((x, y + thumb_h + 2), row["screen_id"], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def train(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    screen_rows = limit_rows(read_csv(args.screens), args.max_screens)
    annotations = read_csv(args.annotations)
    allowed_screen_ids = {row["screen_id"] for row in screen_rows}
    boxes_by_screen: dict[str, list[list[float]]] = defaultdict(list)
    for ann in annotations:
        if ann["screen_id"] in allowed_screen_ids:
            boxes_by_screen[ann["screen_id"]].append(parse_box(ann))

    splits = assign_splits(screen_rows, args.seed, args.val_ratio, args.test_ratio)
    assigned_fields = list(screen_rows[0].keys()) if screen_rows else []
    write_csv(output_dir / "assigned_screens.csv", screen_rows, assigned_fields)
    split_summary = {
        name: {
            "screens": len(rows),
            "positive_screens": sum(1 for row in rows if boxes_by_screen.get(row["screen_id"])),
            "negative_screens": sum(1 for row in rows if not boxes_by_screen.get(row["screen_id"])),
            "boxes": sum(len(boxes_by_screen.get(row["screen_id"], [])) for row in rows),
            "groups": len({row.get("split_group") or row["screen_id"] for row in rows}),
        }
        for name, rows in splits.items()
    }
    if args.split_only:
        summary = {"mode": "split_only", "split_summary": split_summary}
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    device = torch.device(args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    model = make_model(num_classes=2).to(device)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=1e-4)
    train_loader = DataLoader(
        AdsDetectorDataset(splits["train"], boxes_by_screen),
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate,
        num_workers=0,
    )

    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        batches = 0
        for images, targets, _rows in train_loader:
            images = [image.to(device) for image in images]
            targets = [{key: value.to(device) for key, value in target.items()} for target in targets]
            loss_dict = model(images, targets)
            loss = sum(value for value in loss_dict.values())
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            batches += 1
        avg_loss = total_loss / max(batches, 1)
        history.append({"epoch": epoch, "train_loss": avg_loss})
        print(f"epoch={epoch} train_loss={avg_loss:.4f}")

    checkpoint = output_dir / "best.pt"
    torch.save(
        {
            "model": model.state_dict(),
            "model_name": "fasterrcnn_mobilenet_v3_large_320_fpn",
            "num_classes": 2,
            "args": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        },
        checkpoint,
    )
    eval_summary = evaluate(model, splits["test"], boxes_by_screen, device, args.score_threshold, args.iou_threshold, output_dir)
    summary = {
        "dataset": {"screens": str(args.screens), "annotations": str(args.annotations)},
        "device": str(device),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "max_screens": args.max_screens,
        "split_summary": split_summary,
        "eval": eval_summary,
        "checkpoint": str(checkpoint),
        "history": history,
        "warning": "Smoke trainer only. Uses randomly initialized detector weights unless this script is extended with pretrained detection weights.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a small Ads action-candidate detector smoke model.")
    parser.add_argument("--screens", type=Path, default=Path("vision_platform/ads/datasets/detector/action_candidate_20260719/screens.csv"))
    parser.add_argument("--annotations", type=Path, default=Path("vision_platform/ads/datasets/detector/action_candidate_20260719/annotations.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/detector_smoke/action_candidate_seed42"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--score-threshold", type=float, default=0.2)
    parser.add_argument("--iou-threshold", type=float, default=0.3)
    parser.add_argument("--max-screens", type=int, default=0, help="Limit screens for smoke runs. 0 means all screens.")
    parser.add_argument("--split-only", action="store_true")
    train(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
