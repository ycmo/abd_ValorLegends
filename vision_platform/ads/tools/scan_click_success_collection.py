from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from torchvision import models, transforms
from torchvision.models import MobileNet_V3_Small_Weights


FAMILIES = ["x_mark", "play_triangle", "google_play", "next", "free", "got", "arrow"]

EXPECTED_BY_PROPOSAL_SOURCE = {
    "close_template": "x_mark",
    "close_glyph": "x_mark",
    "close_x_classifier": "x_mark",
    "geometry_x": "x_mark",
    "free_ad_template": "free",
    "got_template": "got",
    "google_play_template": "google_play",
    "next_template": "next",
}

EXPECTED_BY_TEMPLATE_NAME = {
    # Runtime keeps this under close templates because it is actionable for ad
    # closing, but visually it is a ">> Ad" chevron/text family, not an X.
    "close_11.png": "arrow",
}


def canonical_object(image: Image.Image, output_size: int = 96, object_ratio: float = 0.70) -> Image.Image:
    image = image.convert("RGB")
    target_max = max(1, round(output_size * object_ratio))
    scale = target_max / max(image.width, image.height, 1)
    new_w = max(1, round(image.width * scale))
    new_h = max(1, round(image.height * scale))
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (output_size, output_size), (0, 0, 0))
    canvas.paste(resized, ((output_size - new_w) // 2, (output_size - new_h) // 2))
    return canvas


class CheckpointScorer:
    def __init__(self, checkpoint_path: Path, device: torch.device):
        self.checkpoint_path = checkpoint_path
        self.device = device
        self.model = self._load_model()
        weights = MobileNet_V3_Small_Weights.DEFAULT
        self.transform = transforms.Compose(
            [
                transforms.Resize((96, 96), interpolation=transforms.InterpolationMode.BILINEAR),
                transforms.ToTensor(),
                transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std),
            ]
        )

    def _load_model(self) -> torch.nn.Module:
        checkpoint = torch.load(self.checkpoint_path, map_location=self.device, weights_only=False)
        families = checkpoint.get("families") or FAMILIES
        if list(families) != FAMILIES:
            raise RuntimeError(f"checkpoint family mismatch for {self.checkpoint_path}: {families}")
        model = models.mobilenet_v3_small(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, len(FAMILIES))
        model.load_state_dict(checkpoint["model"])
        model.to(self.device)
        model.eval()
        return model

    @torch.inference_mode()
    def score(self, image: Image.Image) -> dict[str, float]:
        canonical = canonical_object(image)
        tensor = self.transform(canonical).unsqueeze(0).to(self.device)
        probs = torch.sigmoid(self.model(tensor))[0].detach().cpu().numpy()
        return {family: float(probs[index]) for index, family in enumerate(FAMILIES)}


def load_events(collection_root: Path, date: str) -> list[Path]:
    pattern = f"click_success_{date}_*" if date else "click_success_*"
    return sorted(path for path in collection_root.glob(pattern) if path.is_dir() and (path / "event.json").exists())


def read_event(path: Path) -> dict[str, Any]:
    return json.loads((path / "event.json").read_text(encoding="utf-8"))


def score_image(image_path: Path, scorers: list[CheckpointScorer]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    image = Image.open(image_path).convert("RGB")
    per_checkpoint: dict[str, dict[str, float]] = {}
    values = defaultdict(list)
    for scorer in scorers:
        scores = scorer.score(image)
        per_checkpoint[scorer.checkpoint_path.parent.name] = scores
        for family, score in scores.items():
            values[family].append(score)
    mean_scores = {family: float(np.mean(values[family])) for family in FAMILIES}
    return mean_scores, per_checkpoint


def top_family(scores: dict[str, float]) -> tuple[str, float]:
    family = max(scores, key=scores.get)
    return family, scores[family]


def expected_family_for_event(proposal_source: str, template_name: str) -> str:
    by_template = EXPECTED_BY_TEMPLATE_NAME.get(Path(template_name).name.lower())
    if by_template:
        return by_template
    return EXPECTED_BY_PROPOSAL_SOURCE.get(proposal_source, "")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def contact_sheet(rows: list[dict[str, Any]], output: Path, title: str, *, max_items: int = 80) -> None:
    items = rows[:max_items]
    cols, thumb, label_h, pad = 8, 104, 58, 8
    rows_n = max(1, math.ceil(len(items) / cols))
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows_n * (thumb + label_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((pad, 2), title[:140], fill=(20, 20, 20), font=font)
    for pos, row in enumerate(items):
        x = pad + (pos % cols) * (thumb + pad)
        y = pad + (pos // cols) * (thumb + label_h + pad) + pad
        try:
            image = Image.open(row["bbox_crop"]).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        except Exception:
            image = Image.new("RGB", (thumb, thumb), (80, 80, 80))
        sheet.paste(image, (x, y))
        expected = row.get("expected_family") or "-"
        draw.text((x, y + thumb + 2), f"{row['top_family']} {float(row['top_p']):.2f} exp={expected}", fill=(130, 20, 20), font=font)
        draw.text((x, y + thumb + 18), f"{row['proposal_source']} {row.get('template_name','')}"[:28], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 34), str(row["event_id"])[:28], fill=(20, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score click-success collection crops with visual-family checkpoints.")
    parser.add_argument("--collection-root", type=Path, default=Path("vision_platform/ads/runtime_collection/click_success"))
    parser.add_argument("--date", default="")
    parser.add_argument("--checkpoint", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    checkpoints = args.checkpoint or [
        Path("vision_platform/ads/pilot/visual_family_smoke_20260719/development_retrain_single_family_epochs20/run_seed42/best.pt"),
        Path("vision_platform/ads/pilot/visual_family_smoke_20260719/development_retrain_single_family_epochs20/run_seed43/best.pt"),
        Path("vision_platform/ads/pilot/visual_family_smoke_20260719/development_retrain_single_family_epochs20/run_seed44/best.pt"),
    ]
    missing = [str(path) for path in checkpoints if not path.exists()]
    if missing:
        raise SystemExit(f"missing checkpoint(s): {missing}")

    device = torch.device(args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    scorers = [CheckpointScorer(path, device) for path in checkpoints]
    events = load_events(args.collection_root, args.date)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for event_dir in events:
        try:
            event = read_event(event_dir)
            bbox_crop = Path(event.get("bbox_crop") or event_dir / "crops" / "bbox.png")
            if not bbox_crop.exists():
                raise FileNotFoundError(str(bbox_crop))
            scores, per_checkpoint = score_image(bbox_crop, scorers)
            top, top_p = top_family(scores)
            proposal_source = event.get("proposal_source", "")
            template_name = (event.get("metadata") or {}).get("template_name", "")
            expected = expected_family_for_event(proposal_source, template_name)
            row: dict[str, Any] = {
                "event_id": event.get("event_id", event_dir.name),
                "timestamp": event.get("timestamp", ""),
                "source_session": event.get("source_session", ""),
                "proposal_source": proposal_source,
                "template_name": template_name,
                "template_confidence": (event.get("metadata") or {}).get("confidence", ""),
                "expected_family": expected,
                "top_family": top,
                "top_p": top_p,
                "expected_p": scores.get(expected, "") if expected else "",
                "verified_success": event.get("verified_success", ""),
                "screen_change_score": event.get("screen_change_score", ""),
                "bbox": json.dumps((event.get("metadata") or {}).get("bbox", ""), ensure_ascii=False),
                "click_xy": json.dumps(event.get("click_xy", ""), ensure_ascii=False),
                "event_dir": str(event_dir),
                "pre_click": event.get("pre_click_screenshot", ""),
                "post_click": event.get("post_click_screenshot", ""),
                "bbox_crop": str(bbox_crop),
                "bbox_context_crop": event.get("bbox_context_crop", ""),
            }
            for family in FAMILIES:
                row[f"p_{family}"] = scores[family]
            for checkpoint_name, checkpoint_scores in per_checkpoint.items():
                for family in FAMILIES:
                    row[f"{checkpoint_name}_p_{family}"] = checkpoint_scores[family]
            rows.append(row)
        except Exception as exc:  # noqa: BLE001 - keep collection audits non-fatal.
            errors.append({"event_dir": str(event_dir), "error": str(exc)})

    fields = [
        "event_id",
        "timestamp",
        "source_session",
        "proposal_source",
        "template_name",
        "template_confidence",
        "expected_family",
        "top_family",
        "top_p",
        "expected_p",
        "verified_success",
        "screen_change_score",
        "bbox",
        "click_xy",
        "event_dir",
        "pre_click",
        "post_click",
        "bbox_crop",
        "bbox_context_crop",
        *[f"p_{family}" for family in FAMILIES],
        *[f"{path.parent.name}_p_{family}" for path in checkpoints for family in FAMILIES],
    ]
    write_csv(args.output_dir / "click_success_predictions.csv", rows, fields)
    if errors:
        write_csv(args.output_dir / "errors.csv", errors, ["event_dir", "error"])

    proposal_counts = Counter(row["proposal_source"] for row in rows)
    top_counts = Counter(row["top_family"] for row in rows)
    expected_low = [
        row
        for row in rows
        if row.get("expected_family") and row.get("expected_p") != "" and float(row["expected_p"]) < 0.5
    ]
    disagreement = [
        row
        for row in rows
        if row.get("expected_family") and row["top_family"] != row["expected_family"]
    ]
    low_top = sorted(rows, key=lambda row: float(row["top_p"]))
    expected_low_sorted = sorted(expected_low, key=lambda row: float(row["expected_p"]))
    disagreement_sorted = sorted(disagreement, key=lambda row: float(row["top_p"]), reverse=True)

    contact_sheet(low_top, args.output_dir / "contact_sheets" / "low_top_score_success.png", "Click success with lowest top family score")
    contact_sheet(expected_low_sorted, args.output_dir / "contact_sheets" / "expected_family_low_confidence.png", "Click success where expected family p < 0.5")
    contact_sheet(disagreement_sorted, args.output_dir / "contact_sheets" / "expected_vs_top_disagreement.png", "Expected family differs from model top family")
    for family in FAMILIES:
        subset = sorted(
            [row for row in rows if row.get("expected_family") == family],
            key=lambda row: float(row["expected_p"]) if row.get("expected_p") != "" else 999.0,
        )
        if subset:
            contact_sheet(subset, args.output_dir / "contact_sheets" / f"{family}_expected_lowest.png", f"{family} expected, lowest p")

    summary = {
        "collection_root": str(args.collection_root),
        "date": args.date,
        "device": str(device),
        "checkpoints": [str(path) for path in checkpoints],
        "events_found": len(events),
        "scored_events": len(rows),
        "error_events": len(errors),
        "proposal_source_counts": dict(sorted(proposal_counts.items())),
        "top_family_counts": dict(sorted(top_counts.items())),
        "expected_low_confidence_count": len(expected_low),
        "expected_top_disagreement_count": len(disagreement),
        "outputs": {
            "predictions": str(args.output_dir / "click_success_predictions.csv"),
            "contact_sheets": str(args.output_dir / "contact_sheets"),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Click Success Collection Scan",
        "",
        f"- Date filter: `{args.date or 'all'}`",
        f"- Events found: `{len(events)}`",
        f"- Scored events: `{len(rows)}`",
        f"- Error events: `{len(errors)}`",
        f"- Expected family p < 0.5: `{len(expected_low)}`",
        f"- Expected family != model top family: `{len(disagreement)}`",
        "",
        "## Proposal Sources",
        "",
    ]
    for source, count in sorted(proposal_counts.items()):
        lines.append(f"- `{source}`: {count}")
    lines += ["", "## Top Families", ""]
    for family, count in sorted(top_counts.items()):
        lines.append(f"- `{family}`: {count}")
    (args.output_dir / "summary_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
