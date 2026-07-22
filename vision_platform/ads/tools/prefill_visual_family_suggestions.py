from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


FAMILIES = ["x_mark", "play_triangle", "google_play", "next", "free", "got", "arrow"]
REVIEW_LABELS = FAMILIES + ["negative", "other", "uncertain"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def choose_device(name: str):
    import torch

    if name != "auto":
        return torch.device(name)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


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


class VisualFamilyScorer:
    def __init__(self, checkpoint_path: Path, *, device: str = "auto", output_size: int = 96, object_ratio: float = 0.70):
        self.checkpoint_path = checkpoint_path
        self.output_size = output_size
        self.object_ratio = object_ratio
        self.device = choose_device(device)
        self.model = None
        self.transform = None
        self.families = FAMILIES

    def load(self) -> None:
        if self.model is not None:
            return
        import torch
        from torchvision import models, transforms
        from torchvision.models import MobileNet_V3_Small_Weights

        checkpoint = torch.load(self.checkpoint_path, map_location=self.device, weights_only=False)
        families = checkpoint.get("families") or FAMILIES
        if list(families) != FAMILIES:
            raise RuntimeError(f"checkpoint families mismatch: {families} != {FAMILIES}")

        weights = MobileNet_V3_Small_Weights.DEFAULT
        model = models.mobilenet_v3_small(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, len(FAMILIES))
        model.load_state_dict(checkpoint["model"])
        model.to(self.device)
        model.eval()

        self.model = model
        self.transform = transforms.Compose(
            [
                transforms.Resize((self.output_size, self.output_size), interpolation=transforms.InterpolationMode.BILINEAR),
                transforms.ToTensor(),
                transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std),
            ]
        )

    def score(self, image_path: Path) -> dict[str, float]:
        import torch

        self.load()
        assert self.model is not None
        assert self.transform is not None
        image = canonical_object(Image.open(image_path), self.output_size, self.object_ratio)
        with torch.no_grad():
            tensor = self.transform(image).unsqueeze(0).to(self.device)
            probs = torch.sigmoid(self.model(tensor))[0].detach().cpu().numpy()
        return {family: float(probs[index]) for index, family in enumerate(FAMILIES)}


def read_assets(con: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    clauses = ["a.scan_status = 'ok'"]
    params: list[Any] = []
    if args.path_contains:
        clauses.append("a.relative_path LIKE ?")
        params.append(f"%{args.path_contains}%")
    for token in args.exclude_path_contains:
        if token:
            clauses.append("a.relative_path NOT LIKE ?")
            params.append(f"%{token}%")
    if args.source_root:
        clauses.append("a.source_root = ?")
        params.append(args.source_root)
    if args.role:
        clauses.append("a.asset_role = ?")
        params.append(args.role)
    if args.scope:
        clauses.append("a.image_scope = ?")
        params.append(args.scope)
    if args.domain == "ads_shared":
        clauses.append("a.vision_domain IN ('ads', 'shared')")
    elif args.domain != "all":
        clauses.append("a.vision_domain = ?")
        params.append(args.domain)
    where = " AND ".join(clauses)
    return con.execute(
        f"""
        SELECT a.*, v.families AS existing_families, v.review_status AS existing_visual_status
        FROM assets a
        LEFT JOIN visual_family_reviews v ON v.instance_id = a.instance_id
        WHERE {where}
        ORDER BY a.relative_path COLLATE NOCASE
        """,
        params,
    ).fetchall()


def choose_suggestion(probs: dict[str, float], threshold: float, uncertain_low: float, assignment_policy: str) -> list[str]:
    if assignment_policy == "top1":
        if not probs:
            return ["uncertain"]
        top_family = max(probs, key=probs.get)
        return [top_family] if probs[top_family] >= uncertain_low else ["uncertain"]

    selected = [family for family, prob in probs.items() if prob >= threshold]
    if selected:
        return selected
    max_prob = max(probs.values()) if probs else 0.0
    if max_prob >= uncertain_low:
        return ["uncertain"]
    return ["negative"]


def save_visual_review(con: sqlite3.Connection, instance_id: str, families: list[str], note: str) -> None:
    now = utc_now()
    family_text = "|".join(sorted({family for family in families if family in REVIEW_LABELS}))
    con.execute(
        """
        INSERT INTO visual_family_reviews(instance_id, families, review_status, note, created_at, updated_at)
        VALUES (?, ?, 'pending', ?, ?, ?)
        ON CONFLICT(instance_id) DO UPDATE SET
            families=excluded.families,
            review_status='pending',
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (instance_id, family_text, note, now, now),
    )


def ensure_suggestion_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS visual_family_model_suggestions (
            instance_id TEXT PRIMARY KEY REFERENCES assets(instance_id) ON DELETE CASCADE,
            families TEXT NOT NULL DEFAULT '',
            probabilities_json TEXT NOT NULL DEFAULT '{}',
            model_name TEXT NOT NULL DEFAULT '',
            checkpoint_path TEXT NOT NULL DEFAULT '',
            assignment_policy TEXT NOT NULL DEFAULT '',
            threshold REAL NOT NULL DEFAULT 0,
            uncertain_low REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def save_model_suggestion(
    con: sqlite3.Connection,
    instance_id: str,
    families: list[str],
    probs: dict[str, float],
    args: argparse.Namespace,
) -> None:
    ensure_suggestion_table(con)
    now = utc_now()
    family_text = "|".join(sorted({family for family in families if family in REVIEW_LABELS}))
    con.execute(
        """
        INSERT INTO visual_family_model_suggestions(
            instance_id, families, probabilities_json, model_name, checkpoint_path,
            assignment_policy, threshold, uncertain_low, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instance_id) DO UPDATE SET
            families=excluded.families,
            probabilities_json=excluded.probabilities_json,
            model_name=excluded.model_name,
            checkpoint_path=excluded.checkpoint_path,
            assignment_policy=excluded.assignment_policy,
            threshold=excluded.threshold,
            uncertain_low=excluded.uncertain_low,
            updated_at=excluded.updated_at
        """,
        (
            instance_id,
            family_text,
            json.dumps(probs, ensure_ascii=False, sort_keys=True),
            args.checkpoint.name,
            str(args.checkpoint),
            args.assignment_policy,
            args.threshold,
            args.uncertain_low,
            now,
            now,
        ),
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def make_contact_sheet(rows: list[dict[str, Any]], output_path: Path, *, limit: int = 120) -> None:
    if not rows:
        return
    thumb_w, thumb_h = 112, 112
    label_h = 36
    cols = 8
    rows_to_draw = rows[:limit]
    sheet_rows = (len(rows_to_draw) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, sheet_rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, row in enumerate(rows_to_draw):
        x = (index % cols) * thumb_w
        y = (index // cols) * (thumb_h + label_h)
        try:
            image = Image.open(row["original_path"]).convert("RGB")
            image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            sheet.paste(image, (x + (thumb_w - image.width) // 2, y + (thumb_h - image.height) // 2))
        except Exception as exc:
            draw.text((x + 4, y + 4), f"load error\n{exc}", fill=(180, 0, 0), font=font)
        draw.rectangle((x, y, x + thumb_w - 1, y + thumb_h + label_h - 1), outline=(210, 210, 210))
        text = f"{row['suggestion']}\n{row['top_family']} {float(row['top_prob']):.2f}"
        draw.text((x + 3, y + thumb_h + 2), text, fill=(0, 0, 0), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prefill pending Ads visual-family suggestions with the current classifier.")
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--checkpoint", type=Path, default=Path("vision_platform/ads/pilot/visual_family_smoke/strong_negative_ablation/weight_3_seed42/best.pt"))
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/pilot/visual_family_prefill/latest"))
    parser.add_argument("--path-contains", default="")
    parser.add_argument("--exclude-path-contains", action="append", default=[])
    parser.add_argument("--source-root", default="")
    parser.add_argument("--domain", default="ads_shared", choices=["ads_shared", "ads", "shared", "game", "unknown", "all"])
    parser.add_argument("--role", default="candidate_crop")
    parser.add_argument("--scope", default="crop")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--uncertain-low", type=float, default=0.35)
    parser.add_argument("--assignment-policy", choices=["threshold", "top1"], default="threshold")
    parser.add_argument("--output-size", type=int, default=96)
    parser.add_argument("--object-ratio", type=float, default=0.70)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--overwrite-reviewed", action="store_true")
    parser.add_argument(
        "--write-mode",
        choices=["suggestions", "pending-review", "both"],
        default="suggestions",
        help="Write model output to a separate suggestion table, the legacy pending review row, or both.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    if not args.checkpoint.exists():
        raise SystemExit(f"checkpoint not found: {args.checkpoint}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if not args.dry_run:
        backup_dir = args.db.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"vision_review_before_visual_prefill_{stamp}.db"
        shutil.copy2(args.db, backup_path)

    con = open_db(args.db)
    assets = read_assets(con, args)
    scorer = VisualFamilyScorer(args.checkpoint, device=args.device, output_size=args.output_size, object_ratio=args.object_ratio)
    output_rows: list[dict[str, Any]] = []
    skipped_reviewed = 0
    written = 0

    for index, row in enumerate(assets, start=1):
        if row["existing_visual_status"] == "reviewed" and not args.overwrite_reviewed:
            skipped_reviewed += 1
            continue
        image_path = Path(row["original_path"])
        try:
            probs = scorer.score(image_path)
            error = ""
        except Exception as exc:
            probs = {family: 0.0 for family in FAMILIES}
            error = str(exc)
        top_family = max(probs, key=probs.get)
        top_prob = probs[top_family]
        suggestions = ["uncertain"] if error else choose_suggestion(probs, args.threshold, args.uncertain_low, args.assignment_policy)
        note = (
            f"model_prefill policy={args.assignment_policy}; checkpoint={args.checkpoint.name}; threshold={args.threshold:.2f}; "
            f"uncertain_low={args.uncertain_low:.2f}; canonical={args.output_size}px@{args.object_ratio:.2f}; top={top_family}:{top_prob:.3f}"
        )
        if error:
            note += f"; error={error}"
        if not args.dry_run and args.write_mode in {"pending-review", "both"}:
            save_visual_review(con, row["instance_id"], suggestions, note)
        if not args.dry_run and args.write_mode in {"suggestions", "both"}:
            save_model_suggestion(con, row["instance_id"], suggestions, probs, args)
        if not args.dry_run:
            written += 1
        output_row = {
            "instance_id": row["instance_id"],
            "content_id": row["content_id"],
            "relative_path": row["relative_path"],
            "original_path": row["original_path"],
            "existing_families": row["existing_families"] or "",
            "existing_visual_status": row["existing_visual_status"] or "",
            "suggestion": "|".join(suggestions),
            "top_family": top_family,
            "top_prob": f"{top_prob:.5f}",
            "error": error,
            **{f"p_{family}": f"{probs[family]:.5f}" for family in FAMILIES},
        }
        output_rows.append(output_row)
        if index % 100 == 0:
            print(f"scored {index}/{len(assets)}")

    if not args.dry_run:
        con.commit()
    con.close()

    fieldnames = [
        "instance_id",
        "content_id",
        "relative_path",
        "original_path",
        "existing_families",
        "existing_visual_status",
        "suggestion",
        "top_family",
        "top_prob",
        "error",
        *[f"p_{family}" for family in FAMILIES],
    ]
    predictions_path = args.output_dir / "predictions.csv"
    write_csv(predictions_path, output_rows, fieldnames)

    counts = Counter(row["suggestion"] for row in output_rows)
    top_counts = Counter(row["top_family"] for row in output_rows)
    summary = {
        "db": str(args.db),
        "db_backup": str(backup_path) if backup_path else "",
        "checkpoint": str(args.checkpoint),
        "device": str(scorer.device),
        "threshold": args.threshold,
        "uncertain_low": args.uncertain_low,
        "assignment_policy": args.assignment_policy,
        "output_size": args.output_size,
        "object_ratio": args.object_ratio,
        "matched_assets": len(assets),
        "scored_assets": len(output_rows),
        "written_pending_suggestions": written,
        "write_mode": args.write_mode,
        "skipped_reviewed": skipped_reviewed,
        "suggestion_counts": dict(sorted(counts.items())),
        "top_family_counts": dict(sorted(top_counts.items())),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for family in REVIEW_LABELS:
        family_rows = [row for row in output_rows if family in row["suggestion"].split("|")]
        make_contact_sheet(family_rows, args.output_dir / "contact_sheets" / f"{family}.png")
    make_contact_sheet(sorted(output_rows, key=lambda row: float(row["top_prob"]), reverse=True), args.output_dir / "contact_sheets" / "top_probability.png")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"predictions: {predictions_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
