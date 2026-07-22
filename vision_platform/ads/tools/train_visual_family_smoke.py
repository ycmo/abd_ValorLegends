from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
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


FAMILIES = [
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
    image_path: Path
    labels: list[int]
    families: str
    group_key: str
    instance_id: str
    content_id: str
    relative_path: str
    is_confirmed_strong_hard_negative: bool = False
    split: str = ""


class VisualFamilyDataset(Dataset):
    def __init__(self, rows: list[Row], train: bool):
        self.rows = rows
        weights = MobileNet_V3_Small_Weights.DEFAULT
        steps = [
            transforms.Resize((96, 96), interpolation=transforms.InterpolationMode.BILINEAR),
            transforms.ToTensor(),
            transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std),
        ]
        if train:
            steps.insert(1, transforms.ColorJitter(brightness=0.08, contrast=0.08, saturation=0.04))
        self.transform = transforms.Compose(steps)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        image = Image.open(row.image_path).convert("RGB")
        labels = torch.tensor(row.labels, dtype=torch.float32)
        return self.transform(image), labels, index


def is_none_of_the_above(row: Row) -> bool:
    return not any(row.labels)


def load_content_ids(path: Path | None) -> set[str]:
    if path is None or not str(path) or not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_family_hard_negative_specs(specs: list[str]) -> dict[str, tuple[set[str], float]]:
    parsed: dict[str, tuple[set[str], float]] = {}
    for spec in specs:
        parts = spec.split(":", 2)
        if len(parts) != 3:
            raise SystemExit(
                "--family-hard-negative-spec must be formatted as family:path:weight, "
                f"got: {spec}"
            )
        family, path_text, weight_text = parts
        if family not in FAMILIES:
            raise SystemExit(f"unknown family in --family-hard-negative-spec: {family}")
        path = Path(path_text)
        if not path.exists():
            raise SystemExit(f"family hard-negative file not found: {path}")
        try:
            weight = float(weight_text)
        except ValueError as exc:
            raise SystemExit(f"invalid family hard-negative weight: {weight_text}") from exc
        if weight < 1.0:
            raise SystemExit("--family-hard-negative-spec weight must be >= 1.0")
        ids = load_content_ids(path)
        parsed[family] = (ids, weight)
    return parsed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_boolish(value: str | int | None) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def read_manifest(path: Path) -> list[Row]:
    rows: list[Row] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            labels = [int(raw.get(f"label_{family}") or 0) for family in FAMILIES]
            rows.append(
                Row(
                    image_path=Path(raw["image_path"]),
                    labels=labels,
                    families=raw.get("families", ""),
                    group_key=raw.get("group_key") or raw.get("content_id") or raw["image_path"],
                    instance_id=raw.get("instance_id", ""),
                    content_id=raw.get("content_id", ""),
                    relative_path=raw.get("relative_path", ""),
                    is_confirmed_strong_hard_negative=parse_boolish(raw.get("is_confirmed_strong_hard_negative")),
                    split=(raw.get("split") or "").lower(),
                )
            )
    return rows


def connected_split_groups(rows: list[Row]) -> dict[str, str]:
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for row in rows:
        group_node = f"group:{row.group_key}"
        content_node = f"content:{row.content_id}" if row.content_id else f"instance:{row.instance_id}"
        union(group_node, content_node)

    components: dict[str, list[str]] = defaultdict(list)
    for item in list(parent):
        components[find(item)].append(item)

    node_to_component: dict[str, str] = {}
    for index, (_root, nodes) in enumerate(sorted(components.items(), key=lambda item: sorted(item[1])[0])):
        component = f"component:{index:06d}"
        for node in nodes:
            node_to_component[node] = component

    row_components: dict[str, str] = {}
    for row in rows:
        component = node_to_component[find(f"group:{row.group_key}")]
        row_components[row.instance_id or f"{row.image_path}:{len(row_components)}"] = component
    return row_components


def group_labels(rows: list[Row], row_components: dict[str, str]) -> dict[str, np.ndarray]:
    grouped: dict[str, np.ndarray] = {}
    for row in rows:
        component = row_components[row.instance_id or f"{row.image_path}:{len(grouped)}"]
        current = grouped.setdefault(component, np.zeros(len(FAMILIES), dtype=np.int64))
        current[:] = np.maximum(current, np.array(row.labels, dtype=np.int64))
    return grouped


def assign_splits(rows: list[Row], seed: int, val_ratio: float, test_ratio: float) -> dict[str, list[Row]]:
    valid_splits = {"train", "val", "test"}
    row_components = connected_split_groups(rows)
    explicit_by_component: dict[str, str] = {}
    for row in rows:
        if not row.split:
            continue
        if row.split not in valid_splits:
            raise SystemExit(f"invalid split '{row.split}' for group {row.group_key}, content {row.content_id}")
        component = row_components[row.instance_id or f"{row.image_path}:{len(explicit_by_component)}"]
        existing = explicit_by_component.get(component)
        if existing is not None and existing != row.split:
            raise SystemExit(
                f"conflicting explicit split for connected component {component}: {existing} vs {row.split}; "
                f"group={row.group_key}; content={row.content_id}"
            )
        explicit_by_component[component] = row.split

    all_groups = sorted(set(row_components.values()))
    groups = [group for group in all_groups if group not in explicit_by_component]
    labels_by_group = group_labels(rows, row_components)
    best_groups: tuple[set[str], set[str]] | None = None
    best_score: tuple[int, int, int] | None = None
    rng = random.Random(seed)
    if groups:
        for attempt in range(200):
            shuffled = groups[:]
            rng.seed(seed + attempt)
            rng.shuffle(shuffled)
            n = len(shuffled)
            n_test = max(1, round(n * test_ratio)) if n >= 3 else 0
            n_val = max(1, round(n * val_ratio)) if n >= 3 else 0
            test = set(shuffled[:n_test])
            val = set(shuffled[n_test : n_test + n_val])
            train = set(shuffled[n_test + n_val :])

            split_group_sets = {
                "train": set(train),
                "val": set(val),
                "test": set(test),
            }
            for group, split in explicit_by_component.items():
                split_group_sets[split].add(group)

            score_parts = []
            for split_name in ("train", "val", "test"):
                counts = np.zeros(len(FAMILIES), dtype=np.int64)
                for group in split_group_sets[split_name]:
                    counts += labels_by_group[group]
                score_parts.append(int((counts > 0).sum()))
            score = (score_parts[1] + score_parts[2], score_parts[0], min(score_parts))
            if best_score is None or score > best_score:
                best_score = score
                best_groups = (val, test)
    else:
        best_groups = (set(), set())
    assert best_groups is not None
    val_groups, test_groups = best_groups
    splits = {"train": [], "val": [], "test": []}
    for row in rows:
        component = row_components[row.instance_id or f"{row.image_path}:{len(splits)}"]
        if component in explicit_by_component:
            row.split = explicit_by_component[component]
        elif component in test_groups:
            row.split = "test"
        elif component in val_groups:
            row.split = "val"
        else:
            row.split = "train"
        splits[row.split].append(row)
    validate_no_split_leakage(rows)
    return splits


def validate_no_split_leakage(rows: list[Row]) -> None:
    by_content: dict[str, set[str]] = defaultdict(set)
    by_group: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.content_id:
            by_content[row.content_id].add(row.split)
        if row.group_key:
            by_group[row.group_key].add(row.split)
    content_conflicts = {key: sorted(value) for key, value in by_content.items() if len(value) > 1}
    group_conflicts = {key: sorted(value) for key, value in by_group.items() if len(value) > 1}
    if content_conflicts:
        sample = list(content_conflicts.items())[:10]
        raise SystemExit(f"content_id crosses splits: {sample}")
    if group_conflicts:
        sample = list(group_conflicts.items())[:10]
        raise SystemExit(f"group_key crosses splits: {sample}")


def build_model(device: torch.device) -> nn.Module:
    weights = MobileNet_V3_Small_Weights.DEFAULT
    model = models.mobilenet_v3_small(weights=weights)
    for param in model.parameters():
        param.requires_grad = False
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, len(FAMILIES))
    return model.to(device)


def pos_weight(rows: list[Row], device: torch.device) -> torch.Tensor:
    labels = np.array([row.labels for row in rows], dtype=np.float32)
    pos = labels.sum(axis=0)
    neg = labels.shape[0] - pos
    weights = np.where(pos > 0, neg / np.maximum(pos, 1), 1.0)
    return torch.tensor(weights, dtype=torch.float32, device=device)


def sample_weights_for_rows(rows: list[Row], strong_negative_weight: float) -> np.ndarray:
    weights = np.ones(len(rows), dtype=np.float32)
    if strong_negative_weight == 1.0:
        return weights
    for index, row in enumerate(rows):
        if is_none_of_the_above(row) and row.is_confirmed_strong_hard_negative:
            weights[index] = float(strong_negative_weight)
    return weights


def family_loss_weights_for_rows(rows: list[Row], specs: dict[str, tuple[set[str], float]]) -> np.ndarray:
    weights = np.ones((len(rows), len(FAMILIES)), dtype=np.float32)
    if not specs:
        return weights
    for family, (content_ids, weight) in specs.items():
        family_index = FAMILIES.index(family)
        for row_index, row in enumerate(rows):
            if row.content_id in content_ids and row.labels[family_index] == 0:
                weights[row_index, family_index] = float(weight)
    return weights


def evaluate(model: nn.Module, rows: list[Row], device: torch.device, batch_size: int, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    dataset = VisualFamilyDataset(rows, train=False)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    y_true = np.zeros((len(rows), len(FAMILIES)), dtype=np.float32)
    y_prob = np.zeros((len(rows), len(FAMILIES)), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        for images, labels, indices in loader:
            images = images.to(device)
            probs = torch.sigmoid(model(images)).cpu().numpy()
            idx = indices.numpy()
            y_true[idx] = labels.numpy()
            y_prob[idx] = probs
    return y_true, y_prob


def metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> list[dict[str, float | int | str]]:
    y_pred = (y_prob >= threshold).astype(np.float32)
    rows = []
    for i, family in enumerate(FAMILIES):
        true = y_true[:, i]
        pred = y_pred[:, i]
        tp = int(((true == 1) & (pred == 1)).sum())
        fp = int(((true == 0) & (pred == 1)).sum())
        tn = int(((true == 0) & (pred == 0)).sum())
        fn = int(((true == 1) & (pred == 0)).sum())
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        rows.append(
            {
                "family": family,
                "support": int(true.sum()),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
        )
    return rows


def none_of_the_above_stats(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> dict[str, float | int]:
    if len(y_true) == 0:
        return {
            "support": 0,
            "false_activation_count": 0,
            "correct_abstain_count": 0,
            "false_activation_rate": 0.0,
        }
    mask = y_true.sum(axis=1) == 0
    support = int(mask.sum())
    if support == 0:
        return {
            "support": 0,
            "false_activation_count": 0,
            "correct_abstain_count": 0,
            "false_activation_rate": 0.0,
        }
    max_prob = y_prob[mask].max(axis=1)
    false_activation = int((max_prob >= threshold).sum())
    correct_abstain = support - false_activation
    return {
        "support": support,
        "false_activation_count": false_activation,
        "correct_abstain_count": correct_abstain,
        "false_activation_rate": round(false_activation / max(support, 1), 4),
    }


def none_of_the_above_family_stats(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> list[dict[str, float | int | str]]:
    mask = y_true.sum(axis=1) == 0
    support = int(mask.sum())
    rows: list[dict[str, float | int | str]] = []
    for index, family in enumerate(FAMILIES):
        if support:
            activations = int((y_prob[mask, index] >= threshold).sum())
            rate = activations / support
            mean_prob = float(y_prob[mask, index].mean())
            max_prob = float(y_prob[mask, index].max())
        else:
            activations = 0
            rate = 0.0
            mean_prob = 0.0
            max_prob = 0.0
        rows.append(
            {
                "family": family,
                "none_support": support,
                "false_activation_count": activations,
                "false_activation_rate": round(rate, 4),
                "mean_prob_on_none": round(mean_prob, 5),
                "max_prob_on_none": round(max_prob, 5),
            }
        )
    return rows


def quantile(values: np.ndarray, q: float) -> float:
    if values.size == 0:
        return 0.0
    return float(np.quantile(values, q))


def probability_distribution_rows(y_true: np.ndarray, y_prob: np.ndarray) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    none_mask = y_true.sum(axis=1) == 0
    for index, family in enumerate(FAMILIES):
        scopes = {
            "positive": y_true[:, index] == 1,
            "family_negative": y_true[:, index] == 0,
            "none_of_the_above": none_mask,
        }
        for scope, mask in scopes.items():
            values = y_prob[mask, index]
            rows.append(
                {
                    "family": family,
                    "scope": scope,
                    "count": int(values.size),
                    "mean": round(float(values.mean()) if values.size else 0.0, 5),
                    "min": round(float(values.min()) if values.size else 0.0, 5),
                    "p10": round(quantile(values, 0.10), 5),
                    "p25": round(quantile(values, 0.25), 5),
                    "p50": round(quantile(values, 0.50), 5),
                    "p75": round(quantile(values, 0.75), 5),
                    "p90": round(quantile(values, 0.90), 5),
                    "p95": round(quantile(values, 0.95), 5),
                    "max": round(float(values.max()) if values.size else 0.0, 5),
                }
            )
    return rows


def write_predictions(rows: list[Row], y_true: np.ndarray, y_prob: np.ndarray, output: Path) -> None:
    fields = [
        "image_path",
        "families",
        "split",
        "instance_id",
        "content_id",
        "relative_path",
        *[f"true_{family}" for family in FAMILIES],
        *[f"p_{family}" for family in FAMILIES],
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i, row in enumerate(rows):
            writer.writerow(
                {
                    "image_path": str(row.image_path),
                    "families": row.families,
                    "split": row.split,
                    "instance_id": row.instance_id,
                    "content_id": row.content_id,
                    "relative_path": row.relative_path,
                    **{f"true_{family}": int(y_true[i, j]) for j, family in enumerate(FAMILIES)},
                    **{f"p_{family}": f"{float(y_prob[i, j]):.5f}" for j, family in enumerate(FAMILIES)},
                }
            )


def write_assigned_manifest(rows: list[Row], output: Path) -> None:
    fields = [
        "image_path",
        "families",
        *[f"label_{family}" for family in FAMILIES],
        "split",
        "group_key",
        "instance_id",
        "content_id",
        "relative_path",
        "is_confirmed_strong_hard_negative",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "image_path": str(row.image_path),
                    "families": row.families,
                    **{f"label_{family}": int(row.labels[index]) for index, family in enumerate(FAMILIES)},
                    "split": row.split,
                    "group_key": row.group_key,
                    "instance_id": row.instance_id,
                    "content_id": row.content_id,
                    "relative_path": row.relative_path,
                    "is_confirmed_strong_hard_negative": int(row.is_confirmed_strong_hard_negative),
                }
            )


def contact_sheet(rows: list[Row], y_true: np.ndarray, y_prob: np.ndarray, output: Path, *, false_positive: bool, threshold: float, max_items: int = 120) -> None:
    items: list[tuple[float, int, str]] = []
    y_pred = y_prob >= threshold
    for i in range(len(rows)):
        for j, family in enumerate(FAMILIES):
            if false_positive and y_true[i, j] == 0 and y_pred[i, j]:
                items.append((float(y_prob[i, j]), i, family))
            if not false_positive and y_true[i, j] == 1 and not y_pred[i, j]:
                items.append((float(1.0 - y_prob[i, j]), i, family))
    items.sort(reverse=True)
    items = items[:max_items]
    cols, thumb, label_h, pad = 8, 96, 45, 8
    rows_n = max(1, math.ceil(len(items) / cols))
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for pos, (_score, row_index, family) in enumerate(items):
        x = pad + (pos % cols) * (thumb + pad)
        y = pad + (pos // cols) * (thumb + label_h + pad)
        try:
            image = Image.open(rows[row_index].image_path).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        except Exception:
            image = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(image, (x, y))
        prob = y_prob[row_index, FAMILIES.index(family)]
        draw.text((x, y + thumb + 2), f"{family} p={prob:.2f}", fill=(130, 20, 20), font=font)
        draw.text((x, y + thumb + 18), rows[row_index].families[:20], fill=(20, 20, 20), font=font)
    sheet.save(output)


def write_metrics_csv(rows: list[dict[str, float | int | str]], output: Path) -> None:
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_dict_rows(rows: list[dict[str, float | int | str]], output: Path) -> None:
    if not rows:
        return
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def split_count_summary(splits: dict[str, list[Row]]) -> dict[str, dict[str, int | dict[str, int]]]:
    return {
        name: {
            "rows": len(items),
            "family_counts": dict(Counter(family for row in items for family in row.families.split("|") if family)),
            "groups": len({row.group_key for row in items}),
            "contents": len({row.content_id for row in items}),
            "strong_negative_rows": int(
                sum(1 for row in items if is_none_of_the_above(row) and row.is_confirmed_strong_hard_negative)
            ),
            "strong_negative_contents": int(
                len({row.content_id for row in items if is_none_of_the_above(row) and row.is_confirmed_strong_hard_negative})
            ),
        }
        for name, items in splits.items()
    }


def base_run_summary(args: argparse.Namespace, splits: dict[str, list[Row]], output_dir: Path) -> dict[str, object]:
    return {
        "families": FAMILIES,
        "threshold": args.threshold,
        "seed": args.seed,
        "val_ratio": args.val_ratio,
        "test_ratio": args.test_ratio,
        "source_manifest": str(args.manifest),
        "source_manifest_sha256": sha256_file(args.manifest),
        "trainer_path": str(Path(__file__)),
        "trainer_sha256": sha256_file(Path(__file__)),
        "split_counts": split_count_summary(splits),
        "strong_negative_weight": args.strong_negative_weight,
        "strong_negative_content_ids_file": str(args.strong_negative_content_ids) if args.strong_negative_content_ids else "",
        "family_hard_negative_specs": args.family_hard_negative_spec,
        "manifest_strong_negative_content_ids_count": len(
            {
                row.content_id
                for items in splits.values()
                for row in items
                if row.is_confirmed_strong_hard_negative
            }
        ),
        "assigned_manifest": str(output_dir / "assigned_manifest.csv"),
    }


def train(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_manifest(args.manifest)
    splits = assign_splits(rows, args.seed, args.val_ratio, args.test_ratio)
    family_hard_negative_specs = load_family_hard_negative_specs(args.family_hard_negative_spec)
    manifest_strong_negative_content_ids = {
        row.content_id
        for row in rows
        if row.is_confirmed_strong_hard_negative
    }
    external_strong_negative_content_ids = load_content_ids(args.strong_negative_content_ids)
    if args.strong_negative_content_ids is not None and manifest_strong_negative_content_ids != external_strong_negative_content_ids:
        missing_from_manifest = sorted(external_strong_negative_content_ids - manifest_strong_negative_content_ids)
        missing_from_external = sorted(manifest_strong_negative_content_ids - external_strong_negative_content_ids)
        raise SystemExit(
            "strong hard-negative content id mismatch between manifest and external file; "
            f"missing_from_manifest={missing_from_manifest[:10]}; missing_from_external={missing_from_external[:10]}"
        )
    invalid_strong_rows = [
        row
        for row in rows
        if row.is_confirmed_strong_hard_negative and not is_none_of_the_above(row)
    ]
    if invalid_strong_rows:
        sample = [(row.instance_id, row.content_id, row.families) for row in invalid_strong_rows[:10]]
        raise SystemExit(f"confirmed hard negative has positive family label: {sample}")
    write_assigned_manifest(rows, output_dir / "assigned_manifest.csv")
    if args.split_only:
        summary = {
            **base_run_summary(args, splits, output_dir),
            "mode": "split_only",
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    device = torch.device(args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    model = build_model(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight(splits["train"], device), reduction="none")
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=1e-4)
    train_loader = DataLoader(VisualFamilyDataset(splits["train"], train=True), batch_size=args.batch_size, shuffle=True, num_workers=0)
    train_sample_weights = torch.tensor(
        sample_weights_for_rows(splits["train"], args.strong_negative_weight),
        dtype=torch.float32,
        device=device,
    )
    train_family_loss_weights = torch.tensor(
        family_loss_weights_for_rows(splits["train"], family_hard_negative_specs),
        dtype=torch.float32,
        device=device,
    )

    best_val = -1.0
    best_path = output_dir / "best.pt"
    checkpoint_args = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        for images, labels, indices in train_loader:
            images = images.to(device)
            labels = labels.to(device)
            batch_weights = train_sample_weights[indices.to(device)].view(-1, 1)
            batch_family_weights = train_family_loss_weights[indices.to(device)]
            optimizer.zero_grad(set_to_none=True)
            loss = (criterion(model(images), labels) * batch_weights * batch_family_weights).mean()
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * images.size(0)
        val_true, val_prob = evaluate(model, splits["val"], device, args.batch_size, args.threshold)
        val_metrics = metrics(val_true, val_prob, args.threshold)
        macro_f1 = float(np.mean([row["f1"] for row in val_metrics]))
        history.append({"epoch": epoch, "loss": total_loss / max(len(splits["train"]), 1), "val_macro_f1": macro_f1})
        if macro_f1 > best_val:
            best_val = macro_f1
            torch.save({"model": model.state_dict(), "families": FAMILIES, "args": checkpoint_args}, best_path)
        print(f"epoch={epoch} loss={history[-1]['loss']:.4f} val_macro_f1={macro_f1:.4f}")

    checkpoint = torch.load(best_path, map_location=device)
    model.load_state_dict(checkpoint["model"])
    test_true, test_prob = evaluate(model, splits["test"], device, args.batch_size, args.threshold)
    test_metrics = metrics(test_true, test_prob, args.threshold)
    test_none_of_the_above = none_of_the_above_stats(test_true, test_prob, args.threshold)
    test_none_of_the_above_family = none_of_the_above_family_stats(test_true, test_prob, args.threshold)
    test_probability_distribution = probability_distribution_rows(test_true, test_prob)
    write_metrics_csv(test_metrics, output_dir / "test_metrics.csv")
    write_dict_rows(test_none_of_the_above_family, output_dir / "test_none_of_the_above_family_metrics.csv")
    write_dict_rows(test_probability_distribution, output_dir / "test_probability_distribution.csv")
    write_predictions(splits["test"], test_true, test_prob, output_dir / "test_predictions.csv")
    contact_sheet(splits["test"], test_true, test_prob, output_dir / "false_positive_contact_sheet.png", false_positive=True, threshold=args.threshold)
    contact_sheet(splits["test"], test_true, test_prob, output_dir / "false_negative_contact_sheet.png", false_positive=False, threshold=args.threshold)
    (output_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        **base_run_summary(args, splits, output_dir),
        "device": str(device),
        "test_metrics": test_metrics,
        "test_none_of_the_above": test_none_of_the_above,
        "test_none_of_the_above_family": test_none_of_the_above_family,
        "best_checkpoint": str(best_path),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    split_counts = summary["split_counts"]
    lines = ["# Ads Visual Family Smoke Test", "", f"Device: `{device}`", "", "## Split Counts"]
    for name, info in split_counts.items():
        lines.append(f"- {name}: {info['rows']} rows, {info['groups']} groups, {info['family_counts']}")
    lines += ["", "## Test Metrics", "", "| family | support | precision | recall | f1 | fp | fn |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in test_metrics:
        lines.append(f"| {row['family']} | {row['support']} | {row['precision']} | {row['recall']} | {row['f1']} | {row['fp']} | {row['fn']} |")
    lines += [
        "",
        "## None-of-the-above Check",
        "",
        f"- Support: {test_none_of_the_above['support']}",
        f"- False activation count: {test_none_of_the_above['false_activation_count']}",
        f"- False activation rate: {test_none_of_the_above['false_activation_rate']}",
        f"- Strong hard negative weight: {args.strong_negative_weight}",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/dataset/manifest.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/run_seed42"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--strong-negative-content-ids", type=Path, default=None)
    parser.add_argument("--strong-negative-weight", type=float, default=1.0)
    parser.add_argument(
        "--family-hard-negative-spec",
        action="append",
        default=[],
        help="Per-family negative loss weight as family:path:weight. Content ids in path get extra loss only when that family label is 0.",
    )
    parser.add_argument("--split-only", action="store_true")
    train(parser.parse_args())


if __name__ == "__main__":
    main()
