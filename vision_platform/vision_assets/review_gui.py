from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImageReader, QKeySequence, QPainter, QPen, QPixmap
from PIL import Image
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


DOMAINS = ["ads", "game", "shared", "unknown"]
ASSET_TYPES = ["clean_fullscreen", "annotated_fullscreen", "crop", "sheet", "template", "ignore", "uncertain"]
REPRESENTATIONS = ["raw", "edge_glyph", "binary_mask", "grayscale", "annotated", "debug_overlay", "unknown"]
SCREEN_STATES = ["actionable", "waiting", "returned_to_game", "uncertain"]
SAMPLE_ROLES = ["action_target", "non_action_target", "reference_only", "uncertain"]
BBOX_LABELS = ["positive", "negative", "uncertain"]
CLASS_PURPOSES = ["detector", "classifier"]
VISUAL_FAMILY_OPTIONS = [
    ("X mark / X 叉號", "x_mark"),
    ("Play triangle / 播放三角", "play_triangle"),
    ("Google Play", "google_play"),
    ("Next / 下一步", "next"),
    ("Free / 免費", "free"),
    ("Got / 獲得", "got"),
    ("Arrow / 箭頭", "arrow"),
    ("Negative / 負樣本", "negative"),
    ("Other / 其他", "other"),
    ("Uncertain / 不確定", "uncertain"),
]
DEFAULT_SUB_ROLES = {
    "game": ["play", "got", "free", "other"],
    "shared": ["play", "got", "free", "other"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def text_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


@lru_cache(maxsize=4096)
def image_sort_signature(path_text: str) -> tuple:
    try:
        with Image.open(path_text) as image:
            image = image.convert("RGB").resize((8, 8), Image.Resampling.BILINEAR)
            pixels = np.asarray(image, dtype=np.uint8).reshape(-1, 3)
    except Exception:
        return (999, path_text.lower())

    means = tuple(int(value) for value in pixels.mean(axis=0))
    brightness = sum(means) // 3
    quantized_pixels = tuple(
        tuple(int(channel) // 32 for channel in pixel)
        for pixel in pixels
    )
    # Put broad color/brightness groups first, then the tiny 8x8 color layout.
    return (brightness // 16, means[0] // 16, means[1] // 16, means[2] // 16, quantized_pixels, path_text.lower())


@dataclass
class Asset:
    instance_id: str
    content_id: str
    original_path: str
    relative_path: str
    filename: str
    source_root: str
    vision_domain: str
    asset_role: str
    image_scope: str
    width: int
    height: int


@dataclass
class DetectorProposal:
    x: float
    y: float
    w: float
    h: float
    source: str
    score: str
    candidate_id: str


class ReviewDatabase:
    def __init__(self, db_path: Path, inventory_csv: Path):
        self.db_path = db_path
        self.inventory_csv = inventory_csv
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.db_path.parent / "backups").mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.init_schema()
        self.seed_classes()
        self.import_inventory()
        self.backfill_review_representations()

    def close(self) -> None:
        self.conn.close()

    def backup(self) -> Path | None:
        if not self.db_path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.parent / "backups" / f"vision_review_{stamp}.db"
        shutil.copy2(self.db_path, backup_path)
        return backup_path

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                instance_id TEXT PRIMARY KEY,
                content_id TEXT NOT NULL,
                asset_id TEXT,
                original_path TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                filename TEXT,
                extension TEXT,
                parent_directory TEXT,
                source_root TEXT,
                width INTEGER,
                height INTEGER,
                file_size_bytes INTEGER,
                modified_time TEXT,
                sha256 TEXT,
                duplicate_group TEXT,
                vision_domain TEXT,
                asset_role TEXT,
                image_scope TEXT,
                scan_status TEXT,
                scan_error TEXT
            );

            CREATE TABLE IF NOT EXISTS image_reviews (
                instance_id TEXT PRIMARY KEY REFERENCES assets(instance_id) ON DELETE CASCADE,
                vision_domain TEXT NOT NULL DEFAULT 'unknown',
                asset_type TEXT NOT NULL DEFAULT 'uncertain',
                representation TEXT NOT NULL DEFAULT 'unknown',
                class_id INTEGER REFERENCES classes(id),
                label TEXT NOT NULL DEFAULT 'positive',
                screen_state TEXT NOT NULL DEFAULT 'uncertain',
                candidate_label TEXT NOT NULL DEFAULT 'uncertain',
                sample_role TEXT NOT NULL DEFAULT 'uncertain',
                sub_role TEXT NOT NULL DEFAULT '',
                review_status TEXT NOT NULL DEFAULT 'pending',
                has_no_target INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vision_domain TEXT NOT NULL,
                purpose TEXT NOT NULL,
                name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(vision_domain, purpose, name)
            );

            CREATE TABLE IF NOT EXISTS bboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT NOT NULL REFERENCES assets(instance_id) ON DELETE CASCADE,
                content_id TEXT NOT NULL,
                original_path TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                w REAL NOT NULL,
                h REAL NOT NULL,
                vision_domain TEXT NOT NULL DEFAULT 'unknown',
                class_id INTEGER REFERENCES classes(id),
                label TEXT NOT NULL DEFAULT 'uncertain',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS visual_family_reviews (
                instance_id TEXT PRIMARY KEY REFERENCES assets(instance_id) ON DELETE CASCADE,
                families TEXT NOT NULL DEFAULT '',
                review_status TEXT NOT NULL DEFAULT 'pending',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_assets_content ON assets(content_id);
            CREATE INDEX IF NOT EXISTS idx_assets_domain ON assets(vision_domain);
            CREATE INDEX IF NOT EXISTS idx_bboxes_instance ON bboxes(instance_id);
            CREATE INDEX IF NOT EXISTS idx_bboxes_content ON bboxes(content_id);
            CREATE INDEX IF NOT EXISTS idx_visual_family_status ON visual_family_reviews(review_status);
            """
        )
        self.ensure_schema_migrations()
        self.conn.commit()

    def ensure_schema_migrations(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(image_reviews)").fetchall()}
        if "representation" not in columns:
            self.conn.execute("ALTER TABLE image_reviews ADD COLUMN representation TEXT NOT NULL DEFAULT 'unknown'")
        if "class_id" not in columns:
            self.conn.execute("ALTER TABLE image_reviews ADD COLUMN class_id INTEGER REFERENCES classes(id)")
        if "label" not in columns:
            self.conn.execute("ALTER TABLE image_reviews ADD COLUMN label TEXT NOT NULL DEFAULT 'positive'")
        if "screen_state" not in columns:
            self.conn.execute("ALTER TABLE image_reviews ADD COLUMN screen_state TEXT NOT NULL DEFAULT 'uncertain'")
        if "candidate_label" not in columns:
            self.conn.execute("ALTER TABLE image_reviews ADD COLUMN candidate_label TEXT NOT NULL DEFAULT 'uncertain'")
        if "sample_role" not in columns:
            self.conn.execute("ALTER TABLE image_reviews ADD COLUMN sample_role TEXT NOT NULL DEFAULT 'uncertain'")
            self.conn.execute(
                """
                UPDATE image_reviews
                SET sample_role = CASE candidate_label
                    WHEN 'not_action_target' THEN 'non_action_target'
                    WHEN 'action_target' THEN 'action_target'
                    WHEN 'uncertain' THEN 'uncertain'
                    ELSE 'uncertain'
                END
                """
            )
        if "sub_role" not in columns:
            self.conn.execute("ALTER TABLE image_reviews ADD COLUMN sub_role TEXT NOT NULL DEFAULT ''")
        self.conn.execute("UPDATE image_reviews SET sample_role = 'non_action_target' WHERE sample_role = 'not_action_target'")

    def seed_classes(self) -> None:
        defaults = [
            ("ads", "classifier", "close"),
            ("ads", "classifier", "skip"),
            ("ads", "classifier", "claim"),
            ("ads", "classifier", "continue"),
            ("ads", "classifier", "action_target"),
            ("ads", "classifier", "non_action_target"),
            ("ads", "detector", "actionable_ui"),
            ("ads", "detector", "action_target"),
            ("ads", "detector", "visual_candidate"),
            ("game", "classifier", "task_button"),
            ("game", "classifier", "claim_button"),
            ("game", "classifier", "back_button"),
            ("game", "classifier", "popup_close"),
            ("game", "classifier", "scene_state"),
            ("game", "detector", "interactive_ui"),
        ]
        now = utc_now()
        for domain, purpose, name in defaults:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO classes(vision_domain, purpose, name, active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (domain, purpose, name, now, now),
            )
        self.conn.commit()

    def import_inventory(self) -> None:
        if not self.inventory_csv.exists():
            raise FileNotFoundError(f"Inventory CSV not found: {self.inventory_csv}")
        with self.inventory_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        fields = [
            "instance_id",
            "content_id",
            "asset_id",
            "original_path",
            "relative_path",
            "filename",
            "extension",
            "parent_directory",
            "source_root",
            "width",
            "height",
            "file_size_bytes",
            "modified_time",
            "sha256",
            "duplicate_group",
            "vision_domain",
            "asset_role",
            "image_scope",
            "scan_status",
            "scan_error",
        ]
        for row in rows:
            values = [row.get(field, "") for field in fields]
            self.conn.execute(
                f"""
                INSERT INTO assets({", ".join(fields)})
                VALUES ({", ".join("?" for _ in fields)})
                ON CONFLICT(instance_id) DO UPDATE SET
                    content_id=excluded.content_id,
                    asset_id=excluded.asset_id,
                    original_path=excluded.original_path,
                    relative_path=excluded.relative_path,
                    filename=excluded.filename,
                    extension=excluded.extension,
                    parent_directory=excluded.parent_directory,
                    source_root=excluded.source_root,
                    width=excluded.width,
                    height=excluded.height,
                    file_size_bytes=excluded.file_size_bytes,
                    modified_time=excluded.modified_time,
                    sha256=excluded.sha256,
                    duplicate_group=excluded.duplicate_group,
                    vision_domain=excluded.vision_domain,
                    asset_role=excluded.asset_role,
                    image_scope=excluded.image_scope,
                    scan_status=excluded.scan_status,
                    scan_error=excluded.scan_error
                """,
                values,
            )
        self.conn.commit()

    def backfill_review_representations(self) -> None:
        rows = self.conn.execute(
            """
            SELECT
                r.instance_id,
                r.asset_type,
                r.representation,
                a.relative_path,
                a.asset_role,
                a.image_scope
            FROM image_reviews r
            JOIN assets a ON a.instance_id = r.instance_id
            WHERE r.representation IS NULL OR r.representation = '' OR r.representation = 'unknown'
            """
        ).fetchall()
        changed = 0
        for row in rows:
            inferred = infer_representation(row["relative_path"], row["asset_type"], row["asset_role"], row["image_scope"])
            if inferred != "unknown":
                self.conn.execute(
                    "UPDATE image_reviews SET representation = ?, updated_at = ? WHERE instance_id = ?",
                    (inferred, utc_now(), row["instance_id"]),
                )
                changed += 1
        if changed:
            self.conn.commit()
        self.backfill_sample_roles()

    def backfill_sample_roles(self) -> None:
        rows = self.conn.execute(
            """
            SELECT
                r.instance_id,
                r.asset_type,
                r.representation,
                r.candidate_label,
                r.sample_role,
                a.image_scope
            FROM image_reviews r
            JOIN assets a ON a.instance_id = r.instance_id
            WHERE r.sample_role IS NULL
               OR r.sample_role = ''
               OR r.sample_role = 'uncertain'
               OR r.sample_role = 'not_action_target'
            """
        ).fetchall()
        changed = 0
        for row in rows:
            if row["sample_role"] == "not_action_target" or row["candidate_label"] == "not_action_target":
                role = "non_action_target"
            elif row["candidate_label"] == "action_target":
                role = default_sample_role(row["asset_type"], row["image_scope"], row["representation"])
            else:
                role = default_sample_role(row["asset_type"], row["image_scope"], row["representation"])
            if role != row["sample_role"]:
                self.conn.execute(
                    "UPDATE image_reviews SET sample_role = ?, candidate_label = ?, updated_at = ? WHERE instance_id = ?",
                    (role, legacy_candidate_label_from_sample_role(role), utc_now(), row["instance_id"]),
                )
                changed += 1
        if changed:
            self.conn.commit()

    def query_assets(
        self,
        domain: str = "all",
        role: str = "all",
        scope: str = "all",
        source_root: str = "all",
        reviewed_filter: str = "all",
        visual_review_filter: str = "all",
        visual_family_filter: str = "all",
        search: str = "",
    ) -> list[Asset]:
        clauses = ["a.scan_status = 'ok'"]
        params: list[Any] = []
        if domain == "ads_shared":
            clauses.append("a.vision_domain IN ('ads', 'shared')")
        elif domain != "all":
            clauses.append("a.vision_domain = ?")
            params.append(domain)
        if role != "all":
            clauses.append("a.asset_role = ?")
            params.append(role)
        if scope != "all":
            clauses.append("a.image_scope = ?")
            params.append(scope)
        if source_root != "all":
            clauses.append("a.source_root = ?")
            params.append(source_root)
        if reviewed_filter == "unreviewed":
            clauses.append(
                """
                (r.review_status IS NULL OR r.review_status = 'pending')
                AND NOT EXISTS (
                    SELECT 1
                    FROM assets a2
                    JOIN image_reviews r2 ON r2.instance_id = a2.instance_id
                    WHERE a2.content_id = a.content_id
                      AND r2.review_status = 'reviewed'
                )
                """
            )
        elif reviewed_filter in {"pending", "pending instance"}:
            clauses.append("(r.review_status IS NULL OR r.review_status = 'pending')")
        elif reviewed_filter == "reviewed":
            clauses.append("r.review_status = 'reviewed'")
        elif reviewed_filter == "postponed":
            clauses.append("r.review_status = 'postponed'")
        if visual_review_filter == "unreviewed":
            clauses.append("(vf.review_status IS NULL OR vf.review_status <> 'reviewed')")
        elif visual_review_filter == "reviewed":
            clauses.append("vf.review_status = 'reviewed'")
        elif visual_review_filter == "postponed":
            clauses.append("vf.review_status = 'postponed'")
        if visual_family_filter and visual_family_filter != "all":
            clauses.append("('|' || COALESCE(vf.families, '') || '|') LIKE ?")
            params.append(f"%|{visual_family_filter}|%")
        if search:
            clauses.append("(a.relative_path LIKE ? OR a.filename LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"""
            SELECT a.*
            FROM assets a
            LEFT JOIN image_reviews r ON r.instance_id = a.instance_id
            LEFT JOIN visual_family_reviews vf ON vf.instance_id = a.instance_id
            WHERE {where}
            ORDER BY a.relative_path COLLATE NOCASE
            """,
            params,
        ).fetchall()
        return [self.row_to_asset(row) for row in rows]

    def row_to_asset(self, row: sqlite3.Row) -> Asset:
        return Asset(
            instance_id=row["instance_id"],
            content_id=row["content_id"],
            original_path=row["original_path"],
            relative_path=row["relative_path"],
            filename=row["filename"],
            source_root=row["source_root"],
            vision_domain=row["vision_domain"] or "unknown",
            asset_role=row["asset_role"] or "unknown",
            image_scope=row["image_scope"] or "unknown",
            width=int(row["width"] or 0),
            height=int(row["height"] or 0),
        )

    def source_roots(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT source_root FROM assets ORDER BY source_root").fetchall()
        return [row[0] for row in rows]

    def roles(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT asset_role FROM assets ORDER BY asset_role").fetchall()
        return [row[0] for row in rows if row[0]]

    def scopes(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT image_scope FROM assets ORDER BY image_scope").fetchall()
        return [row[0] for row in rows if row[0]]

    def sub_roles(self, domain: str | None = None) -> list[str]:
        params: list[Any] = []
        where = "WHERE sub_role IS NOT NULL AND TRIM(sub_role) <> ''"
        if domain in {"game", "shared"}:
            where += " AND vision_domain = ?"
            params.append(domain)
        rows = self.conn.execute(
            f"SELECT DISTINCT sub_role FROM image_reviews {where} ORDER BY sub_role COLLATE NOCASE",
            params,
        ).fetchall()
        return [row[0] for row in rows if row[0]]

    def get_review(self, instance_id: str, asset: Asset) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM image_reviews WHERE instance_id = ?", (instance_id,)).fetchone()
        if row is None:
            now = utc_now()
            asset_type = scope_to_asset_type(asset.image_scope, asset.asset_role)
            representation = infer_representation(asset.relative_path, asset_type, asset.asset_role, asset.image_scope)
            self.conn.execute(
                """
                INSERT INTO image_reviews(instance_id, vision_domain, asset_type, representation, label, candidate_label, sample_role, screen_state, review_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'positive', ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    instance_id,
                    asset.vision_domain if asset.vision_domain in DOMAINS else "ads",
                    asset_type,
                    representation,
                    default_candidate_label(asset_type, asset.image_scope),
                    default_sample_role(asset_type, asset.image_scope, representation),
                    default_screen_state(asset_type, asset.image_scope),
                    now,
                    now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM image_reviews WHERE instance_id = ?", (instance_id,)).fetchone()
        elif not row["representation"] or row["representation"] == "unknown":
            inferred = infer_representation(asset.relative_path, row["asset_type"], asset.asset_role, asset.image_scope)
            if inferred != "unknown":
                self.conn.execute(
                    "UPDATE image_reviews SET representation = ?, updated_at = ? WHERE instance_id = ?",
                    (inferred, utc_now(), instance_id),
                )
                self.conn.commit()
                row = self.conn.execute("SELECT * FROM image_reviews WHERE instance_id = ?", (instance_id,)).fetchone()
        return row

    def get_visual_review(self, instance_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM visual_family_reviews WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()

    def save_visual_review(self, instance_id: str, families: list[str], status: str, note: str = "") -> None:
        now = utc_now()
        family_text = "|".join(sorted({family.strip() for family in families if family.strip()}))
        self.conn.execute(
            """
            INSERT INTO visual_family_reviews(instance_id, families, review_status, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
                families=excluded.families,
                review_status=excluded.review_status,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (instance_id, family_text, status, note, now, now),
        )
        self.conn.commit()

    def save_review(
        self,
        instance_id: str,
        domain: str,
        asset_type: str,
        representation: str,
        class_id: int | None,
        label: str,
        screen_state: str,
        sample_role: str,
        sub_role: str,
        status: str,
        no_target: bool,
        note: str,
    ) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO image_reviews(instance_id, vision_domain, asset_type, representation, class_id, label, screen_state, candidate_label, sample_role, sub_role, review_status, has_no_target, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
                vision_domain=excluded.vision_domain,
                asset_type=excluded.asset_type,
                representation=excluded.representation,
                class_id=excluded.class_id,
                label=excluded.label,
                screen_state=excluded.screen_state,
                candidate_label=excluded.candidate_label,
                sample_role=excluded.sample_role,
                sub_role=excluded.sub_role,
                review_status=excluded.review_status,
                has_no_target=excluded.has_no_target,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (
                instance_id,
                domain,
                asset_type,
                representation,
                class_id,
                label,
                screen_state,
                legacy_candidate_label_from_sample_role(sample_role),
                sample_role,
                sub_role.strip(),
                status,
                1 if no_target else 0,
                note,
                now,
                now,
            ),
        )
        self.conn.commit()

    def content_duplicate_count(self, content_id: str, instance_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM assets WHERE content_id = ? AND instance_id <> ?",
            (content_id, instance_id),
        ).fetchone()
        return int(row[0])

    def classes(self, include_inactive: bool = False) -> list[sqlite3.Row]:
        where = "" if include_inactive else "WHERE active = 1"
        return self.conn.execute(
            f"SELECT * FROM classes {where} ORDER BY vision_domain, purpose, name"
        ).fetchall()

    def add_class(self, domain: str, purpose: str, name: str) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO classes(vision_domain, purpose, name, active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (domain, purpose, name.strip(), now, now),
        )
        self.conn.commit()

    def rename_class(self, class_id: int, new_name: str) -> None:
        self.conn.execute("UPDATE classes SET name = ?, updated_at = ? WHERE id = ?", (new_name.strip(), utc_now(), class_id))
        self.conn.commit()

    def set_class_active(self, class_id: int, active: bool) -> None:
        self.conn.execute("UPDATE classes SET active = ?, updated_at = ? WHERE id = ?", (1 if active else 0, utc_now(), class_id))
        self.conn.commit()

    def class_usage_count(self, class_id: int) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM bboxes WHERE class_id = ?", (class_id,)).fetchone()
        return int(row[0])

    def bboxes(self, instance_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT b.*, c.name AS class_name
            FROM bboxes b
            LEFT JOIN classes c ON c.id = b.class_id
            WHERE b.instance_id = ?
            ORDER BY b.id
            """,
            (instance_id,),
        ).fetchall()

    def visual_candidate_class_id(self) -> int:
        row = self.conn.execute(
            "SELECT id FROM classes WHERE vision_domain = 'ads' AND purpose = 'detector' AND name = 'visual_candidate'"
        ).fetchone()
        if row is None:
            self.add_class("ads", "detector", "visual_candidate")
            row = self.conn.execute(
                "SELECT id FROM classes WHERE vision_domain = 'ads' AND purpose = 'detector' AND name = 'visual_candidate'"
            ).fetchone()
        return int(row["id"])

    def action_target_class_id(self) -> int:
        return self.visual_candidate_class_id()

    def create_bbox(self, asset: Asset, rect: QRectF, domain: str = "ads", note: str = "") -> int:
        now = utc_now()
        class_id = self.visual_candidate_class_id()
        self.conn.execute(
            """
            INSERT INTO bboxes(instance_id, content_id, original_path, x, y, w, h, vision_domain, class_id, label, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'positive', ?, ?, ?)
            """,
            (
                asset.instance_id,
                asset.content_id,
                asset.original_path,
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height(),
                domain,
                class_id,
                note,
                now,
                now,
            ),
        )
        bbox_id = int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        self.conn.commit()
        return bbox_id

    def update_bbox_rect(self, bbox_id: int, rect: QRectF) -> None:
        self.conn.execute(
            "UPDATE bboxes SET x = ?, y = ?, w = ?, h = ?, updated_at = ? WHERE id = ?",
            (rect.x(), rect.y(), rect.width(), rect.height(), utc_now(), bbox_id),
        )
        self.conn.commit()

    def update_bbox_metadata(self, bbox_id: int, domain: str, class_id: int | None, label: str, note: str) -> None:
        self.conn.execute(
            """
            UPDATE bboxes
            SET vision_domain = ?, class_id = ?, label = ?, note = ?, updated_at = ?
            WHERE id = ?
            """,
            (domain, class_id, label, note, utc_now(), bbox_id),
        )
        self.conn.commit()

    def delete_bbox(self, bbox_id: int) -> None:
        self.conn.execute("DELETE FROM bboxes WHERE id = ?", (bbox_id,))
        self.conn.commit()

    def delete_bboxes_for_instance(self, instance_id: str) -> None:
        self.conn.execute("DELETE FROM bboxes WHERE instance_id = ?", (instance_id,))
        self.conn.commit()

    def counts(self) -> dict[str, int]:
        result = {}
        for key, query in {
            "assets": "SELECT COUNT(*) FROM assets",
            "reviews": "SELECT COUNT(*) FROM image_reviews WHERE review_status = 'reviewed'",
            "pending": "SELECT COUNT(*) FROM assets a LEFT JOIN image_reviews r ON r.instance_id = a.instance_id WHERE r.review_status IS NULL OR r.review_status = 'pending'",
            "visual_reviews": "SELECT COUNT(*) FROM visual_family_reviews WHERE review_status = 'reviewed'",
            "visual_pending": "SELECT COUNT(*) FROM assets a LEFT JOIN visual_family_reviews v ON v.instance_id = a.instance_id WHERE v.review_status IS NULL OR v.review_status = 'pending'",
            "bboxes": "SELECT COUNT(*) FROM bboxes",
        }.items():
            result[key] = int(self.conn.execute(query).fetchone()[0])
        return result

    def export_csv_json(self, export_dir: Path) -> list[Path]:
        export_dir.mkdir(parents=True, exist_ok=True)
        bbox_rows = self.conn.execute(
            """
            SELECT
                b.id AS bbox_id,
                b.instance_id,
                b.content_id,
                b.original_path,
                a.relative_path,
                b.x, b.y, b.w, b.h,
                b.vision_domain,
                r.asset_type,
                r.representation,
                r.screen_state,
                r.candidate_label,
                r.sample_role,
                r.sub_role,
                c.name AS class_name,
                c.purpose AS class_purpose,
                b.label,
                b.note,
                b.created_at,
                b.updated_at
            FROM bboxes b
            LEFT JOIN assets a ON a.instance_id = b.instance_id
            LEFT JOIN image_reviews r ON r.instance_id = b.instance_id
            LEFT JOIN classes c ON c.id = b.class_id
            ORDER BY b.instance_id, b.id
            """
        ).fetchall()
        review_rows = self.conn.execute(
            """
            SELECT
                r.instance_id,
                a.content_id,
                a.original_path,
                a.relative_path,
                r.vision_domain,
                r.asset_type,
                r.representation,
                r.label,
                r.screen_state,
                r.candidate_label,
                r.sample_role,
                r.sub_role,
                c.name AS class_name,
                c.purpose AS class_purpose,
                r.review_status,
                r.has_no_target,
                r.note,
                r.created_at,
                r.updated_at
            FROM image_reviews r
            LEFT JOIN assets a ON a.instance_id = r.instance_id
            LEFT JOIN classes c ON c.id = r.class_id
            ORDER BY a.relative_path COLLATE NOCASE
            """
        ).fetchall()
        visual_rows = self.conn.execute(
            """
            SELECT
                v.instance_id,
                a.content_id,
                a.original_path,
                a.relative_path,
                a.vision_domain,
                a.asset_role,
                a.image_scope,
                r.asset_type,
                r.representation,
                v.families,
                v.review_status,
                v.note,
                v.created_at,
                v.updated_at
            FROM visual_family_reviews v
            LEFT JOIN assets a ON a.instance_id = v.instance_id
            LEFT JOIN image_reviews r ON r.instance_id = v.instance_id
            ORDER BY a.relative_path COLLATE NOCASE
            """
        ).fetchall()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bbox_csv_path = export_dir / f"bbox_annotations_{stamp}.csv"
        bbox_json_path = export_dir / f"bbox_annotations_{stamp}.json"
        review_csv_path = export_dir / f"image_reviews_{stamp}.csv"
        review_json_path = export_dir / f"image_reviews_{stamp}.json"
        visual_csv_path = export_dir / f"visual_family_reviews_{stamp}.csv"
        visual_json_path = export_dir / f"visual_family_reviews_{stamp}.json"
        bbox_fields = bbox_rows[0].keys() if bbox_rows else [
            "bbox_id",
            "instance_id",
            "content_id",
            "original_path",
            "relative_path",
            "x",
            "y",
            "w",
            "h",
            "vision_domain",
            "asset_type",
            "representation",
            "screen_state",
            "candidate_label",
            "sample_role",
            "sub_role",
            "class_name",
            "class_purpose",
            "label",
            "note",
            "created_at",
            "updated_at",
        ]
        review_fields = review_rows[0].keys() if review_rows else [
            "instance_id",
            "content_id",
            "original_path",
            "relative_path",
            "vision_domain",
            "asset_type",
            "representation",
            "label",
            "screen_state",
            "candidate_label",
            "sample_role",
            "sub_role",
            "class_name",
            "class_purpose",
            "review_status",
            "has_no_target",
            "note",
            "created_at",
            "updated_at",
        ]
        visual_fields = visual_rows[0].keys() if visual_rows else [
            "instance_id",
            "content_id",
            "original_path",
            "relative_path",
            "vision_domain",
            "asset_role",
            "image_scope",
            "asset_type",
            "representation",
            "families",
            "review_status",
            "note",
            "created_at",
            "updated_at",
        ]
        with bbox_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(bbox_fields))
            writer.writeheader()
            for row in bbox_rows:
                writer.writerow(dict(row))
        bbox_json_path.write_text(json.dumps([dict(row) for row in bbox_rows], ensure_ascii=False, indent=2), encoding="utf-8")
        with review_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(review_fields))
            writer.writeheader()
            for row in review_rows:
                writer.writerow(dict(row))
        review_json_path.write_text(json.dumps([dict(row) for row in review_rows], ensure_ascii=False, indent=2), encoding="utf-8")
        with visual_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(visual_fields))
            writer.writeheader()
            for row in visual_rows:
                writer.writerow(dict(row))
        visual_json_path.write_text(json.dumps([dict(row) for row in visual_rows], ensure_ascii=False, indent=2), encoding="utf-8")
        return [bbox_csv_path, bbox_json_path, review_csv_path, review_json_path, visual_csv_path, visual_json_path]


def scope_to_asset_type(image_scope: str, asset_role: str) -> str:
    if asset_role == "template":
        return "template"
    if image_scope == "fullscreen":
        return "clean_fullscreen"
    if image_scope == "crop":
        return "crop"
    if image_scope == "sheet_or_composite":
        return "sheet"
    return "uncertain"


def infer_representation(relative_path: str, asset_type: str, asset_role: str, image_scope: str) -> str:
    p = relative_path.replace("\\", "/").lower()
    name = Path(p).name
    if "debug_overlay" in p or "overlay" in name or "marked" in name:
        return "debug_overlay"
    if "annotated" in p or "annotated" in name or "框" in relative_path:
        return "annotated"
    if "close_glyphs" in p and ("edge" in name or "glyph" in name):
        return "edge_glyph"
    if "edge" in name and ("glyph" in p or "close_glyph" in p):
        return "edge_glyph"
    if "mask" in name or "binary" in name:
        return "binary_mask"
    if "gray" in name or "grayscale" in name:
        return "grayscale"
    if asset_type in {"clean_fullscreen", "template", "crop"} and asset_role not in {"debug_output", "model_output"}:
        return "raw"
    if image_scope == "sheet_or_composite":
        return "annotated" if "review" in p or "contact" in p else "unknown"
    return "unknown"


def default_candidate_label(asset_type: str, image_scope: str) -> str:
    if asset_type in {"crop", "template"} or image_scope == "crop":
        return "action_target"
    return "uncertain"


def default_sample_role(asset_type: str, image_scope: str, representation: str) -> str:
    if asset_type not in {"crop", "template"} and image_scope != "crop":
        return "uncertain"
    if representation in {"edge_glyph", "binary_mask", "grayscale"}:
        return "reference_only"
    return "action_target"


def legacy_candidate_label_from_sample_role(sample_role: str) -> str:
    if sample_role == "non_action_target":
        return "not_action_target"
    if sample_role == "action_target":
        return "action_target"
    return "uncertain"


def default_screen_state(asset_type: str, image_scope: str) -> str:
    if asset_type in {"crop", "template"} or image_scope == "crop":
        return "uncertain"
    return "actionable"


class ImageView(QGraphicsView):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.pixmap_item: QGraphicsPixmapItem | None = None
        self.main_window: MainWindow | None = None
        self.drawing = False
        self.draw_start = QPointF()
        self.draw_item: QGraphicsRectItem | None = None

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def load_image(self, path: str) -> bool:
        self.scene.clear()
        self.pixmap_item = None
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False
        self.pixmap_item = self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(QRectF(pixmap.rect()))
        self.resetTransform()
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        return True

    def start_bbox_mode(self) -> None:
        self.drawing = True
        self.setDragMode(QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.CrossCursor)

    def stop_bbox_mode(self) -> None:
        self.drawing = False
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.viewport().unsetCursor()
        if self.draw_item is not None:
            self.scene.removeItem(self.draw_item)
            self.draw_item = None

    def mousePressEvent(self, event):
        if self.drawing and event.button() == Qt.LeftButton:
            self.draw_start = self.mapToScene(event.position().toPoint())
            self.draw_item = self.scene.addRect(QRectF(self.draw_start, self.draw_start), QPen(QColor("#00a8ff"), 2))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drawing and self.draw_item is not None:
            current = self.mapToScene(event.position().toPoint())
            self.draw_item.setRect(QRectF(self.draw_start, current).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drawing and event.button() == Qt.LeftButton and self.draw_item is not None:
            rect = self.draw_item.rect().normalized()
            self.scene.removeItem(self.draw_item)
            self.draw_item = None
            self.stop_bbox_mode()
            if rect.width() >= 3 and rect.height() >= 3 and self.main_window is not None:
                self.main_window.create_bbox_from_rect(rect)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class BBoxItem(QGraphicsRectItem):
    def __init__(self, bbox_id: int, rect: QRectF, main_window: "MainWindow"):
        super().__init__(rect)
        self.bbox_id = bbox_id
        self.main_window = main_window
        self.setPen(QPen(QColor("#00d166"), 2))
        self.setBrush(QColor(0, 209, 102, 35))
        self.setFlags(
            QGraphicsRectItem.ItemIsMovable
            | QGraphicsRectItem.ItemIsSelectable
            | QGraphicsRectItem.ItemSendsGeometryChanges
        )

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionHasChanged:
            QTimer.singleShot(0, lambda: self.main_window.save_bbox_item_rect(self))
        if change == QGraphicsRectItem.ItemSelectedHasChanged and value:
            QTimer.singleShot(0, lambda: self.main_window.select_bbox(self.bbox_id))
        return super().itemChange(change, value)

    def image_rect(self) -> QRectF:
        rect = self.rect().translated(self.pos())
        return QRectF(max(0.0, rect.x()), max(0.0, rect.y()), max(1.0, rect.width()), max(1.0, rect.height()))


class RadioButtonPanel(QWidget):
    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QRadioButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for label, value in options:
            button = QRadioButton(label)
            self.group.addButton(button)
            self.buttons[value] = button
            layout.addWidget(button)
        layout.addStretch(1)

    def value(self) -> str:
        for value, button in self.buttons.items():
            if button.isChecked():
                return value
        return ""

    def set_value(self, value: str) -> None:
        button = self.buttons.get(value)
        if button is None and self.buttons:
            button = self.buttons.get("unknown") or next(iter(self.buttons.values()))
        if button is not None:
            button.setChecked(True)

    def set_enabled(self, enabled: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(enabled)

    def on_changed(self, callback) -> None:
        self.group.buttonClicked.connect(lambda _button: callback())


class CheckBoxPanel(QWidget):
    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.buttons: dict[str, QCheckBox] = {}
        self.changed_callbacks: list[Any] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        row: QHBoxLayout | None = None
        for index, (label, value) in enumerate(options):
            if index % 2 == 0:
                row = QHBoxLayout()
                row.setSpacing(8)
                outer.addLayout(row)
            button = QCheckBox(label)
            button.clicked.connect(lambda _checked=False: self.emit_changed())
            self.buttons[value] = button
            row.addWidget(button, 1)
        if row is not None:
            row.addStretch(1)

    def values(self) -> list[str]:
        return [value for value, button in self.buttons.items() if button.isChecked()]

    def set_values(self, values: list[str] | str | None) -> None:
        if isinstance(values, str):
            value_set = {value for value in values.split("|") if value}
        else:
            value_set = set(values or [])
        for value, button in self.buttons.items():
            button.blockSignals(True)
            button.setChecked(value in value_set)
            button.blockSignals(False)

    def on_changed(self, callback) -> None:
        self.changed_callbacks.append(callback)

    def emit_changed(self) -> None:
        for callback in self.changed_callbacks:
            callback()


class ClassButtonPanel(QWidget):
    def __init__(self, db: ReviewDatabase, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = db
        self.domain = "unknown"
        self.purpose = "classifier"
        self.selected_class_id: int | None = None
        self.buttons: dict[int, QPushButton] = {}
        self.changed_callbacks: list[Any] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("Class (必填)")
        outer.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(90)
        self.scroll.setMaximumHeight(190)
        self.inner = QWidget()
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.inner)
        outer.addWidget(self.scroll)

    def on_changed(self, callback) -> None:
        self.changed_callbacks.append(callback)

    def emit_changed(self) -> None:
        for callback in self.changed_callbacks:
            callback()

    def configure(self, domain: str, purpose: str, selected_class_id: int | None = None) -> None:
        self.domain = domain
        self.purpose = purpose
        self.selected_class_id = selected_class_id
        self.refresh()

    def refresh(self) -> None:
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.buttons.clear()
        rows = [
            row
            for row in self.db.classes(include_inactive=False)
            if row["vision_domain"] == self.domain and row["purpose"] == self.purpose
        ]
        if not rows:
            self.selected_class_id = None
            self.inner_layout.addWidget(QLabel(f"No active {self.domain}/{self.purpose} classes"))
            return
        common_order = {
            "close": 0,
            "skip": 1,
            "claim": 2,
            "continue": 3,
            "task_button": 0,
            "claim_button": 1,
            "back_button": 2,
            "popup_close": 3,
            "actionable_ui": 0,
            "interactive_ui": 0,
        }
        rows.sort(key=lambda row: (common_order.get(row["name"], 100), row["name"]))
        for row in rows:
            button = QPushButton(row["name"])
            button.setCheckable(True)
            button.setMinimumHeight(30)
            button.clicked.connect(lambda _checked=False, cid=row["id"]: self.set_selected_class_id(cid, emit=True))
            self.buttons[row["id"]] = button
            self.inner_layout.addWidget(button)
        if self.selected_class_id not in self.buttons:
            self.selected_class_id = None
        self.inner_layout.addStretch(1)
        self.apply_selection()

    def set_selected_class_id(self, class_id: int | None, emit: bool = False) -> None:
        self.selected_class_id = class_id
        self.apply_selection()
        if emit:
            self.emit_changed()

    def apply_selection(self) -> None:
        for class_id, button in self.buttons.items():
            selected = class_id == self.selected_class_id
            button.setChecked(selected)
            if selected:
                button.setStyleSheet("QPushButton { background: #1f6feb; color: white; font-weight: bold; }")
            else:
                button.setStyleSheet("")

    def current_class_id(self) -> int | None:
        return self.selected_class_id


class ClassDialog(QDialog):
    def __init__(self, parent: QWidget, db: ReviewDatabase):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Class Manager")
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["id", "domain", "purpose", "name", "active", "used"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        form = QHBoxLayout()
        self.domain = QComboBox()
        self.domain.addItems(DOMAINS)
        self.purpose = QComboBox()
        self.purpose.addItems(CLASS_PURPOSES)
        self.name = QLineEdit()
        add_btn = QPushButton("Add")
        rename_btn = QPushButton("Rename Selected")
        toggle_btn = QPushButton("Toggle Active")
        form.addWidget(self.domain)
        form.addWidget(self.purpose)
        form.addWidget(self.name)
        form.addWidget(add_btn)
        form.addWidget(rename_btn)
        form.addWidget(toggle_btn)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        layout.addWidget(buttons)
        buttons.rejected.connect(self.reject)
        add_btn.clicked.connect(self.add_class)
        rename_btn.clicked.connect(self.rename_selected)
        toggle_btn.clicked.connect(self.toggle_selected)
        self.refresh()

    def selected_class_id(self) -> int | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        return int(self.table.item(indexes[0].row(), 0).text())

    def refresh(self) -> None:
        rows = self.db.classes(include_inactive=True)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            used = self.db.class_usage_count(row["id"])
            values = [row["id"], row["vision_domain"], row["purpose"], row["name"], row["active"], used]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def add_class(self) -> None:
        name = self.name.text().strip()
        if not name:
            return
        try:
            self.db.add_class(self.domain.currentText(), self.purpose.currentText(), name)
            self.name.clear()
            self.refresh()
        except sqlite3.IntegrityError as exc:
            QMessageBox.warning(self, "Class exists", str(exc))

    def rename_selected(self) -> None:
        class_id = self.selected_class_id()
        name = self.name.text().strip()
        if class_id is None or not name:
            return
        try:
            self.db.rename_class(class_id, name)
            self.refresh()
        except sqlite3.IntegrityError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))

    def toggle_selected(self) -> None:
        class_id = self.selected_class_id()
        if class_id is None:
            return
        row = self.db.conn.execute("SELECT active FROM classes WHERE id = ?", (class_id,)).fetchone()
        self.db.set_class_active(class_id, not bool(row["active"]))
        self.refresh()


class MainWindow(QMainWindow):
    def __init__(self, db: ReviewDatabase, export_dir: Path, gui_config: dict[str, Any] | None = None):
        super().__init__()
        self.db = db
        self.export_dir = export_dir
        self.gui_config = gui_config or {}
        self.project_root = self.export_dir.parent.parent.parent
        self.detector_review_mode = self.gui_config.get("review_mode", "detector") == "detector"
        self.default_filter = self.gui_config.get("default_filter", {})
        self.default_sort_mode = self.gui_config.get("sort_mode", "path")
        self.detector_proposals_by_path = self.load_detector_proposals()
        self.click_bboxes_by_path = self.load_click_success_bboxes()
        self.assets: list[Asset] = []
        self.current_index = -1
        self.current_asset: Asset | None = None
        self.current_asset_type = "uncertain"
        self.bbox_items: dict[int, BBoxItem] = {}
        self.selected_bbox_id: int | None = None
        self.loading_ui = False
        self.sticky_review_state: dict[str, Any] | None = None
        self.apply_sticky_on_next_load = False
        self.saved_asset_history: list[Asset] = []
        self.saved_history_cursor = 0
        self.thumbnail_queue: list[int] = []
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setInterval(15)
        self.thumbnail_timer.timeout.connect(self.load_next_thumbnail_batch)
        self.initial_runtime_filter_applied = False
        self.suspect_records_by_instance = self.load_suspect_records()
        self.suspect_instance_ids = set(self.suspect_records_by_instance)
        self.setWindowTitle("Ads Vision Review - 廣告標註")
        self.setWindowTitle("Vision Candidate Review - Detector BBox Labeling")
        self.resize(1500, 900)
        self.build_ui()
        self.refresh_filters()
        self.apply_filters()
        self.setup_shortcuts()

    def path_key(self, path_text: str) -> str:
        path = Path(path_text)
        if not path.is_absolute():
            path = self.project_root / path
        try:
            path = path.resolve()
        except OSError:
            path = path.absolute()
        return str(path).replace("\\", "/").lower()

    def load_detector_proposals(self) -> dict[str, list[DetectorProposal]]:
        proposals: dict[str, list[DetectorProposal]] = defaultdict(list)
        manifest_text = str(self.gui_config.get("detector_proposals_csv", "")).strip()
        if not manifest_text:
            return proposals
        manifest_path = Path(manifest_text)
        if not manifest_path.is_absolute():
            manifest_path = self.project_root / manifest_path
        if not manifest_path.exists():
            print(f"warning: detector_proposals_csv not found: {manifest_path}")
            return proposals

        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    proposal = DetectorProposal(
                        x=float(row.get("bbox_x", "") or 0),
                        y=float(row.get("bbox_y", "") or 0),
                        w=max(1.0, float(row.get("bbox_w", "") or 0)),
                        h=max(1.0, float(row.get("bbox_h", "") or 0)),
                        source=row.get("proposal_sources", "") or row.get("proposal_source", ""),
                        score=row.get("proposal_score_max", "") or row.get("proposal_scores", ""),
                        candidate_id=row.get("candidate_id", ""),
                    )
                except ValueError:
                    continue
                for key_field in ("parent_screen_path", "source_screen_path"):
                    key_value = row.get(key_field, "").strip()
                    if key_value:
                        proposals[self.path_key(key_value)].append(proposal)
        return proposals

    def load_click_success_bboxes(self) -> dict[str, list[DetectorProposal]]:
        proposals: dict[str, list[DetectorProposal]] = defaultdict(list)
        root_text = str(self.gui_config.get("click_success_root", "")).strip()
        if not root_text:
            root_text = "vision_platform/ads/runtime_collection/click_success"
        click_root = Path(root_text)
        if not click_root.is_absolute():
            click_root = self.project_root / click_root
        if not click_root.exists():
            return proposals

        date_filter = str(self.gui_config.get("click_success_date", "")).strip()
        for event_path in click_root.glob("click_success_*/event.json"):
            if date_filter and date_filter not in event_path.parent.name:
                continue
            try:
                event = json.loads(event_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            bbox = (event.get("detector_training_candidate") or {}).get("bbox")
            if not bbox:
                bbox = (event.get("metadata") or {}).get("bbox")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            parent = event.get("pre_click_screenshot") or event.get("primary_review_image")
            if not parent:
                continue
            try:
                proposal = DetectorProposal(
                    x=float(bbox[0]),
                    y=float(bbox[1]),
                    w=max(1.0, float(bbox[2])),
                    h=max(1.0, float(bbox[3])),
                    source=event.get("proposal_source", "") or (event.get("detector_training_candidate") or {}).get("proposal_source", ""),
                    score=str(event.get("screen_change_score", "")),
                    candidate_id=event_path.parent.name,
                )
            except (TypeError, ValueError):
                continue
            proposals[self.path_key(parent)].append(proposal)
        return proposals

    def build_ui(self) -> None:
        splitter = QSplitter()
        splitter.addWidget(self.build_left_panel())
        self.image_view = ImageView()
        self.image_view.main_window = self
        splitter.addWidget(self.image_view)
        splitter.addWidget(self.build_right_panel())
        splitter.setSizes([320, 850, 330])
        self.setCentralWidget(splitter)

        toolbar = QToolBar("Navigation")
        self.addToolBar(toolbar)
        for text, shortcut, handler in [
            ("上一張", QKeySequence("A"), self.prev_image),
            ("下一張", QKeySequence("D"), self.next_image),
            ("下一張未審查", QKeySequence("Ctrl+D"), self.next_pending),
            ("新增候選框", QKeySequence("B"), self.start_bbox),
            ("刪除候選框", QKeySequence.Delete, self.delete_selected_bbox),
        ]:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(handler)
            toolbar.addAction(action)

    def build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.domain_filter = QComboBox()
        self.domain_filter.addItems(["ads_shared", "ads", "shared", "all", "game", "unknown"])
        self.domain_filter.setCurrentText("ads_shared")
        self.role_filter = QComboBox()
        self.scope_filter = QComboBox()
        self.source_filter = QComboBox()
        self.review_filter = QComboBox()
        self.review_filter.addItems(["unreviewed", "suspect", "pending instance", "all", "reviewed", "postponed"])
        self.visual_review_filter = QComboBox()
        self.visual_review_filter.addItems(["unreviewed", "all", "reviewed", "postponed"])
        self.visual_family_filter = QComboBox()
        self.visual_family_filter.addItems(["all"] + [value for _label, value in VISUAL_FAMILY_OPTIONS])
        self.sort_filter = QComboBox()
        self.sort_filter.addItems(["path", "image_signature", "visual_family"])
        self.suspect_reason_filter = QComboBox()
        self.suspect_reason_filter.addItem("all")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜尋路徑或檔名")
        filter_form = QFormLayout()
        if not self.detector_review_mode:
            filter_form.addRow("Domain", self.domain_filter)
        filter_form.addRow("Role", self.role_filter)
        filter_form.addRow("Scope", self.scope_filter)
        filter_form.addRow("Source", self.source_filter)
        filter_form.addRow("Status", self.review_filter)
        filter_form.addRow("Sort", self.sort_filter)
        filter_form.addRow("Suspect", self.suspect_reason_filter)
        filter_form.addRow("Search", self.search_edit)
        if not self.detector_review_mode:
            filter_form.addRow("Visual review", self.visual_review_filter)
            filter_form.addRow("Family", self.visual_family_filter)
        layout.addLayout(filter_form)
        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)
        self.approve_filtered_btn = QPushButton("Approve Filtered")
        self.approve_filtered_btn.setToolTip("Mark all currently filtered pending visual-family suggestions as reviewed.")
        layout.addWidget(self.approve_filtered_btn)
        self.approve_filtered_btn.setVisible(not self.detector_review_mode)
        self.asset_list = QListWidget()
        self.asset_list.setIconSize(QSize(96, 54))
        self.asset_list.currentRowChanged.connect(self.load_asset_by_index)
        layout.addWidget(self.asset_list, 1)
        for widget in [self.domain_filter, self.role_filter, self.scope_filter, self.source_filter, self.visual_review_filter, self.visual_family_filter, self.sort_filter, self.suspect_reason_filter]:
            widget.currentTextChanged.connect(self.apply_filters)
        self.review_filter.currentTextChanged.connect(self.on_review_filter_changed)
        self.search_edit.textChanged.connect(self.apply_filters)
        self.approve_filtered_btn.clicked.connect(self.approve_filtered_visual_suggestions)
        return panel

    def build_right_panel(self) -> QWidget:
        panel = QWidget()
        outer_layout = QVBoxLayout(panel)
        outer_layout.setContentsMargins(6, 6, 6, 6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll, 1)

        self.workflow_hint = QLabel("請載入圖片")
        self.workflow_hint.setWordWrap(True)
        self.workflow_hint.setStyleSheet("QLabel { font-weight: bold; padding: 6px; background: #eef5ff; }")
        layout.addWidget(self.workflow_hint)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        self.duplicate_label = QLabel("")
        self.duplicate_label.setWordWrap(True)
        layout.addWidget(self.duplicate_label)
        self.suspect_box = QGroupBox("複查提示")
        suspect_layout = QVBoxLayout(self.suspect_box)
        self.suspect_label = QLabel("")
        self.suspect_label.setWordWrap(True)
        suspect_layout.addWidget(self.suspect_label)
        layout.addWidget(self.suspect_box)
        self.suspect_box.setVisible(False)

        review_box = QGroupBox("圖片標註")
        review_layout = QVBoxLayout(review_box)
        self.domain_label = QLabel("領域（自動）：ads")
        review_layout.addWidget(self.domain_label)
        self.review_domain_panel = RadioButtonPanel(
            [("廣告 Ads", "ads"), ("遊戲 Game", "game"), ("共用 Shared", "shared"), ("未判斷 Unknown", "unknown")]
        )
        review_layout.addWidget(self.review_domain_panel)
        self.review_domain_panel.setVisible(not self.detector_review_mode)
        self.sub_role_box = QGroupBox("子類型 / 錨點（Game/Shared，可選）")
        sub_role_layout = QVBoxLayout(self.sub_role_box)
        sub_role_layout.addWidget(QLabel("可直接點選，也可選 other 後輸入自訂子類別。"))
        self.sub_role_quick_panel = RadioButtonPanel(
            [("play", "play"), ("got", "got"), ("free", "free"), ("other", "other")]
        )
        sub_role_layout.addWidget(self.sub_role_quick_panel)
        self.sub_role_combo = QComboBox()
        self.sub_role_combo.setEditable(True)
        self.sub_role_combo.setInsertPolicy(QComboBox.NoInsert)
        self.sub_role_combo.lineEdit().setPlaceholderText("other 的自訂文字，可用中文")
        sub_role_layout.addWidget(self.sub_role_combo)
        review_layout.addWidget(self.sub_role_box)
        self.sub_role_box.setVisible(False)
        self.asset_type_label = QLabel("資產用途（自動）：-")
        self.technical_label = QLabel("")
        self.technical_label.setWordWrap(True)
        self.advanced_image_btn = QPushButton("顯示進階資訊")
        self.advanced_image_btn.setCheckable(True)
        self.advanced_image_box = QGroupBox("進階資訊")
        advanced_image_layout = QVBoxLayout(self.advanced_image_box)
        advanced_image_layout.addWidget(self.asset_type_label)
        advanced_image_layout.addWidget(self.technical_label)
        advanced_image_layout.addWidget(QLabel("影像形式（通常自動判斷，可修正）"))
        self.representation_panel = RadioButtonPanel(
            [
                ("原圖 Raw", "raw"),
                ("邊緣圖 Edge glyph", "edge_glyph"),
                ("遮罩 Mask", "binary_mask"),
                ("灰階 Grayscale", "grayscale"),
                ("人工標記 Annotated", "annotated"),
                ("除錯疊圖 Debug", "debug_overlay"),
                ("未知 Unknown", "unknown"),
            ]
        )
        advanced_image_layout.addWidget(self.representation_panel)
        export_btn = QPushButton("匯出 CSV/JSON")
        advanced_image_layout.addWidget(export_btn)
        review_layout.addWidget(self.advanced_image_btn)
        review_layout.addWidget(self.advanced_image_box)
        review_layout.addWidget(QLabel("備註（可選）"))
        self.image_note = QTextEdit()
        self.image_note.setMinimumHeight(60)
        self.image_note.setMaximumHeight(130)
        self.image_note.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        review_layout.addWidget(self.image_note)
        layout.addWidget(review_box)

        self.classifier_box = QGroupBox("Classifier 樣本（裁切圖 / 模板）")
        classifier_layout = QVBoxLayout(self.classifier_box)
        classifier_layout.addWidget(QLabel("樣本用途（必填）"))
        classifier_help = QLabel("不是要點的相似圖案請標為「干擾樣本」，它會幫 classifier 學會排除 false pattern。")
        classifier_help.setWordWrap(True)
        classifier_layout.addWidget(classifier_help)
        self.classifier_box.setTitle("Visual family 標註")
        for index in range(classifier_layout.count()):
            widget = classifier_layout.itemAt(index).widget()
            if isinstance(widget, QLabel):
                widget.setVisible(False)
        visual_title = QLabel("Visual family（可複選）")
        visual_title.setStyleSheet("QLabel { font-weight: bold; }")
        visual_help = QLabel("只標圖片外觀特徵，不在這裡決定是否點擊。Negative 表示可作為視覺 family 的負樣本。")
        visual_help.setWordWrap(True)
        classifier_layout.addWidget(visual_title)
        classifier_layout.addWidget(visual_help)
        self.visual_family_panel = CheckBoxPanel(VISUAL_FAMILY_OPTIONS)
        classifier_layout.addWidget(self.visual_family_panel)
        self.sample_role_panel = RadioButtonPanel(
            [
                ("要點擊目標", "action_target"),
                ("干擾樣本 / 不是要點", "non_action_target"),
                ("參考 / 錨點（不進二分類）", "reference_only"),
                ("不確定", "uncertain"),
            ]
        )
        classifier_layout.addWidget(self.sample_role_panel)
        self.sample_role_panel.setVisible(False)
        layout.addWidget(self.classifier_box)

        self.screen_box = QGroupBox("完整畫面狀態")
        screen_layout = QVBoxLayout(self.screen_box)
        screen_layout.addWidget(QLabel("畫面狀態（必填）"))
        self.screen_state_panel = RadioButtonPanel(
            [
                ("有候選標記", "actionable"),
                ("沒有候選標記", "waiting"),
                ("略過此圖", "returned_to_game"),
                ("不確定", "uncertain"),
            ]
        )
        screen_layout.addWidget(self.screen_state_panel)
        layout.addWidget(self.screen_box)

        self.detector_box = QGroupBox("Detector 候選框")
        detector_layout = QVBoxLayout(self.detector_box)
        self.detector_instruction = QLabel(
            "Detector 目標是高召回：請框出所有可能需要點擊的位置，寧可多框。"
            "後續 classifier 會判斷是否真的要點。"
        )
        self.detector_instruction.setWordWrap(True)
        detector_layout.addWidget(self.detector_instruction)
        detector_layout.addWidget(QLabel("候選框來源（可選）"))
        self.bbox_source_panel = RadioButtonPanel(
            [
                ("Model", "model"),
                ("Click", "click"),
                ("Previous", "previous"),
                ("Manual only", "manual"),
            ]
        )
        self.bbox_source_panel.set_value(self.gui_config.get("default_bbox_source", "model"))
        detector_layout.addWidget(self.bbox_source_panel)
        self.proposal_count_label = QLabel("")
        detector_layout.addWidget(self.proposal_count_label)
        proposal_row = QHBoxLayout()
        self.apply_model_bboxes_btn = QPushButton("Use model boxes")
        self.apply_click_bboxes_btn = QPushButton("Use click boxes")
        self.apply_previous_bboxes_btn = QPushButton("Use previous boxes")
        proposal_row.addWidget(self.apply_model_bboxes_btn, 1)
        proposal_row.addWidget(self.apply_click_bboxes_btn, 1)
        proposal_row.addWidget(self.apply_previous_bboxes_btn, 1)
        detector_layout.addLayout(proposal_row)
        self.new_bbox_btn = QPushButton("新增候選框")
        detector_layout.addWidget(self.new_bbox_btn)
        layout.addWidget(self.detector_box)

        self.bbox_box = QGroupBox("已選候選框")
        bbox_layout = QVBoxLayout(self.bbox_box)
        self.bbox_domain_auto = QLabel("領域（自動）：-")
        bbox_layout.addWidget(self.bbox_domain_auto)
        self.bbox_class_auto = QLabel("候選框類型（自動）：可能要點擊的位置")
        bbox_layout.addWidget(self.bbox_class_auto)
        bbox_layout.addWidget(QLabel("候選框備註（可選）"))
        self.bbox_x = self.spin()
        self.bbox_y = self.spin()
        self.bbox_w = self.spin()
        self.bbox_h = self.spin()
        self.bbox_note = QTextEdit()
        self.bbox_note.setMinimumHeight(60)
        self.bbox_note.setMaximumHeight(130)
        self.bbox_note.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.delete_bbox_btn = QPushButton("刪除已選候選框")
        bbox_layout.addWidget(self.bbox_note)
        self.advanced_btn = QPushButton("顯示進階座標")
        self.advanced_btn.setCheckable(True)
        bbox_layout.addWidget(self.advanced_btn)
        self.advanced_box = QGroupBox("進階座標（自動）")
        advanced_layout = QFormLayout(self.advanced_box)
        advanced_layout.addRow("x", self.bbox_x)
        advanced_layout.addRow("y", self.bbox_y)
        advanced_layout.addRow("w", self.bbox_w)
        advanced_layout.addRow("h", self.bbox_h)
        bbox_layout.addWidget(self.advanced_box)
        bbox_layout.addWidget(self.delete_bbox_btn)
        layout.addWidget(self.bbox_box)
        layout.addStretch(1)

        self.save_next_btn = QPushButton("Save && Next")
        self.prev_saved_btn = QPushButton("Previous saved")
        self.postpone_btn = QPushButton("Postpone")
        self.save_next_btn.setMinimumHeight(38)
        self.prev_saved_btn.setMinimumHeight(38)
        self.postpone_btn.setMinimumHeight(38)
        self.save_next_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        action_row = QWidget()
        action_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        action_row.setMinimumHeight(52)
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 6, 0, 0)
        action_layout.addWidget(self.save_next_btn, 1)
        action_layout.addWidget(self.prev_saved_btn, 1)
        action_layout.addWidget(self.postpone_btn, 1)
        outer_layout.addWidget(action_row, 0)

        self.representation_panel.on_changed(self.autosave_review)
        self.review_domain_panel.on_changed(self.on_domain_changed)
        self.sub_role_quick_panel.on_changed(self.on_sub_role_quick_changed)
        self.sub_role_combo.currentTextChanged.connect(self.autosave_review)
        self.image_note.textChanged.connect(self.autosave_review)
        self.save_next_btn.clicked.connect(lambda: self.save_review_status("reviewed"))
        self.prev_saved_btn.clicked.connect(self.previous_saved_asset)
        self.postpone_btn.clicked.connect(lambda: self.save_review_status("postponed"))
        for shortcut in ["Ctrl+Return", "Ctrl+Enter"]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ApplicationShortcut)
            action.triggered.connect(lambda _checked=False: self.save_review_status("reviewed"))
            self.addAction(action)
        postpone_action = QAction(self)
        postpone_action.setShortcut(QKeySequence("Ctrl+P"))
        postpone_action.setShortcutContext(Qt.ApplicationShortcut)
        postpone_action.triggered.connect(lambda _checked=False: self.save_review_status("postponed"))
        self.addAction(postpone_action)
        previous_saved_action = QAction(self)
        previous_saved_action.setShortcut(QKeySequence("Ctrl+Left"))
        previous_saved_action.setShortcutContext(Qt.ApplicationShortcut)
        previous_saved_action.triggered.connect(self.previous_saved_asset)
        self.addAction(previous_saved_action)
        self.new_bbox_btn.clicked.connect(self.start_bbox)
        self.apply_model_bboxes_btn.clicked.connect(lambda: self.apply_model_proposals_to_current(replace=True, silent=False))
        self.apply_click_bboxes_btn.clicked.connect(lambda: self.apply_click_bboxes_to_current(replace=True, silent=False))
        self.apply_previous_bboxes_btn.clicked.connect(lambda: self.apply_previous_bboxes_to_current(replace=True, silent=False))
        self.bbox_source_panel.on_changed(self.on_bbox_source_changed)
        self.delete_bbox_btn.clicked.connect(self.delete_selected_bbox)
        self.advanced_btn.toggled.connect(self.toggle_advanced)
        self.advanced_image_btn.toggled.connect(self.toggle_image_details)
        export_btn.clicked.connect(self.export_annotations)
        self.visual_family_panel.on_changed(self.autosave_visual_family)
        self.sample_role_panel.on_changed(self.autosave_review)
        self.screen_state_panel.on_changed(self.on_screen_state_changed)
        for spin in [self.bbox_x, self.bbox_y, self.bbox_w, self.bbox_h]:
            spin.valueChanged.connect(self.autosave_bbox_rect_from_spin)
        self.bbox_note.textChanged.connect(self.autosave_bbox_metadata)
        self.advanced_box.setVisible(False)
        self.advanced_image_box.setVisible(False)
        self.sub_role_box.setVisible(False)
        self.bbox_box.setVisible(False)
        self.prev_saved_btn.setEnabled(False)
        return panel

    def spin(self) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0, 100000)
        box.setDecimals(1)
        return box

    def setup_shortcuts(self) -> None:
        pass

    def refresh_filters(self) -> None:
        self.role_filter.clear()
        self.role_filter.addItems(["all"] + self.db.roles())
        self.scope_filter.clear()
        self.scope_filter.addItems(["all"] + self.db.scopes())
        self.source_filter.clear()
        self.source_filter.addItems(["all"] + self.db.source_roots())
        if not self.initial_runtime_filter_applied:
            self.initial_runtime_filter_applied = True
            domain = self.default_filter.get("domain", "ads")
            role = self.default_filter.get("role", "runtime_collection")
            scope = self.default_filter.get("scope", "fullscreen")
            source = self.default_filter.get("source", "vision_platform\\ads\\runtime_collection")
            status = self.default_filter.get("status", "unreviewed")
            visual_status = self.default_filter.get("visual_status", "unreviewed")
            visual_family = self.default_filter.get("visual_family", "all")
            search = self.default_filter.get("search", "pre_click.png")
            sort_mode = self.default_filter.get("sort", self.default_sort_mode)
            if self.domain_filter.findText(domain) >= 0:
                self.domain_filter.setCurrentText(domain)
            if self.role_filter.findText(role) >= 0:
                self.role_filter.setCurrentText(role)
            if self.scope_filter.findText(scope) >= 0:
                self.scope_filter.setCurrentText(scope)
            runtime_source = source
            if self.source_filter.findText(runtime_source) >= 0:
                self.source_filter.setCurrentText(runtime_source)
            if self.review_filter.findText(status) >= 0:
                self.review_filter.setCurrentText(status)
            if self.visual_review_filter.findText(visual_status) >= 0:
                self.visual_review_filter.setCurrentText(visual_status)
            if self.visual_family_filter.findText(visual_family) >= 0:
                self.visual_family_filter.setCurrentText(visual_family)
            if self.sort_filter.findText(sort_mode) >= 0:
                self.sort_filter.setCurrentText(sort_mode)
            self.search_edit.setText(search)
        current_reason = self.suspect_reason_filter.currentText() if hasattr(self, "suspect_reason_filter") else "all"
        self.suspect_records_by_instance = self.load_suspect_records()
        self.suspect_instance_ids = set(self.suspect_records_by_instance)
        self.suspect_reason_filter.blockSignals(True)
        self.suspect_reason_filter.clear()
        reasons = sorted({record.get("suspect_reason", "") for records in self.suspect_records_by_instance.values() for record in records if record.get("suspect_reason", "")})
        self.suspect_reason_filter.addItems(["all"] + reasons)
        if current_reason and self.suspect_reason_filter.findText(current_reason) >= 0:
            self.suspect_reason_filter.setCurrentText(current_reason)
        self.suspect_reason_filter.blockSignals(False)
        self.refresh_class_combo()

    def refresh_class_combo(self) -> None:
        pass

    def load_suspect_records(self) -> dict[str, list[dict[str, str]]]:
        suspect_path = self.export_dir.parent.parent / "ads" / "audit" / "suspect_annotations.csv"
        if not suspect_path.exists():
            return {}
        records: dict[str, list[dict[str, str]]] = defaultdict(list)
        with suspect_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                instance_id = row.get("instance_id", "").strip()
                if instance_id:
                    records[instance_id].append(row)
        return records

    def on_review_filter_changed(self) -> None:
        if self.review_filter.currentText() == "suspect" and self.domain_filter.currentText() == "ads":
            self.domain_filter.setCurrentText("all")
            return
        self.apply_filters()

    def apply_filters(self) -> None:
        if self.loading_ui:
            return
        reviewed_filter = self.review_filter.currentText()
        self.assets = self.db.query_assets(
            domain=self.domain_filter.currentText(),
            role=self.role_filter.currentText(),
            scope=self.scope_filter.currentText(),
            source_root=self.source_filter.currentText(),
            reviewed_filter="all" if reviewed_filter == "suspect" else reviewed_filter,
            visual_review_filter="all" if self.detector_review_mode else self.visual_review_filter.currentText(),
            visual_family_filter="all" if self.detector_review_mode else self.visual_family_filter.currentText(),
            search=self.search_edit.text().strip(),
        )
        if reviewed_filter == "suspect":
            self.suspect_records_by_instance = self.load_suspect_records()
            self.suspect_instance_ids = set(self.suspect_records_by_instance)
            reason = self.suspect_reason_filter.currentText()
            if reason and reason != "all":
                self.assets = [
                    asset
                    for asset in self.assets
                    if any(record.get("suspect_reason") == reason for record in self.suspect_records_by_instance.get(asset.instance_id, []))
                ]
            else:
                self.assets = [asset for asset in self.assets if asset.instance_id in self.suspect_instance_ids]
        include_path_any = [str(value).lower() for value in self.default_filter.get("include_path_any", []) if str(value).strip()]
        exclude_path_any = [str(value).lower() for value in self.default_filter.get("exclude_path_any", []) if str(value).strip()]
        if include_path_any:
            self.assets = [
                asset
                for asset in self.assets
                if any(token in asset.relative_path.lower() for token in include_path_any)
            ]
        if exclude_path_any:
            self.assets = [
                asset
                for asset in self.assets
                if not any(token in asset.relative_path.lower() for token in exclude_path_any)
            ]
        include_instance_ids = {str(value).strip() for value in self.default_filter.get("include_instance_ids", []) if str(value).strip()}
        include_instance_ids_file = str(self.default_filter.get("include_instance_ids_file", "")).strip()
        if include_instance_ids_file:
            ids_path = Path(include_instance_ids_file)
            if ids_path.exists():
                include_instance_ids.update(
                    line.strip()
                    for line in ids_path.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                )
        if include_instance_ids:
            self.assets = [asset for asset in self.assets if asset.instance_id in include_instance_ids]
        if self.sort_filter.currentText() == "image_signature":
            self.assets.sort(key=lambda asset: image_sort_signature(asset.original_path))
        elif self.sort_filter.currentText() == "visual_family":
            self.assets.sort(key=lambda asset: (self.visual_family_text(asset), image_sort_signature(asset.original_path)))
        self.asset_list.blockSignals(True)
        self.asset_list.clear()
        for i, asset in enumerate(self.assets[:1000]):
            self.asset_list.addItem(self.asset_list_item(asset, with_icon=False))
        self.thumbnail_queue = list(range(min(len(self.assets), 1000)))
        self.asset_list.blockSignals(False)
        self.thumbnail_timer.start()
        counts = self.db.counts()
        shown = min(len(self.assets), 1000)
        self.progress_label.setText(
            f"Filtered: {len(self.assets)} (shown {shown}) | image reviewed {counts['reviews']} | "
            f"visual reviewed {counts['visual_reviews']} | bbox {counts['bboxes']}"
        )
        if self.assets:
            self.asset_list.setCurrentRow(0)
        else:
            self.current_index = -1
            self.current_asset = None

    def asset_list_item(self, asset: Asset, with_icon: bool = False) -> QListWidgetItem:
        family_text = self.visual_family_text(asset) or "-"
        item = QListWidgetItem(f"{asset.filename}\n{family_text}\n{asset.vision_domain} | {asset.asset_role} | {asset.image_scope}")
        if with_icon:
            self.set_item_thumbnail(item, asset)
        item.setToolTip(asset.relative_path)
        return item

    def visual_family_text(self, asset: Asset) -> str:
        row = self.db.get_visual_review(asset.instance_id)
        return row["families"] if row is not None else ""

    def set_item_thumbnail(self, item: QListWidgetItem, asset: Asset) -> None:
        pixmap = QPixmap(asset.original_path)
        if not pixmap.isNull():
            item.setIcon(QIcon(pixmap.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def load_next_thumbnail_batch(self) -> None:
        if not self.thumbnail_queue:
            self.thumbnail_timer.stop()
            return
        for _ in range(12):
            if not self.thumbnail_queue:
                self.thumbnail_timer.stop()
                return
            index = self.thumbnail_queue.pop(0)
            if index >= self.asset_list.count() or index >= len(self.assets):
                continue
            item = self.asset_list.item(index)
            if item is not None:
                self.set_item_thumbnail(item, self.assets[index])

    def remove_current_from_unreviewed_list(self) -> None:
        idx = self.current_index
        if idx < 0 or idx >= len(self.assets) or idx >= self.asset_list.count():
            self.apply_filters()
            return

        reviewed_content_id = self.assets[idx].content_id
        self.asset_list.blockSignals(True)
        if self.review_filter.currentText() == "unreviewed":
            for remove_idx in range(min(len(self.assets), self.asset_list.count()) - 1, -1, -1):
                if self.assets[remove_idx].content_id == reviewed_content_id:
                    self.assets.pop(remove_idx)
                    self.asset_list.takeItem(remove_idx)
            self.assets = [asset for asset in self.assets if asset.content_id != reviewed_content_id]
        else:
            self.assets.pop(idx)
            self.asset_list.takeItem(idx)
        if self.asset_list.count() < 1000 and len(self.assets) > self.asset_list.count():
            append_index = self.asset_list.count()
            self.asset_list.addItem(self.asset_list_item(self.assets[append_index], with_icon=False))
            self.thumbnail_queue.append(append_index)
            self.thumbnail_timer.start()
        self.asset_list.blockSignals(False)

        if self.asset_list.count() == 0:
            self.current_index = -1
            self.current_asset = None
            self.image_view.scene.clear()
            self.path_label.setText("")
            self.technical_label.setText("")
            self.duplicate_label.setText("")
            self.workflow_hint.setText("No unreviewed images in current filter.")
            self.update_progress()
            return

        next_idx = min(idx, self.asset_list.count() - 1)
        self.current_index = -1
        self.asset_list.setCurrentRow(next_idx)
        if self.current_index != next_idx:
            self.load_asset_by_index(next_idx)
        self.update_progress()

    def approve_filtered_visual_suggestions(self) -> None:
        candidates: list[tuple[Asset, sqlite3.Row, sqlite3.Row]] = []
        skipped_no_family = 0
        skipped_reviewed = 0
        skipped_non_classifier = 0
        for asset in self.assets:
            asset_type = scope_to_asset_type(asset.image_scope, asset.asset_role)
            is_classifier = asset_type in {"crop", "template"} or asset.image_scope == "crop" or asset.asset_role == "template"
            if not is_classifier:
                skipped_non_classifier += 1
                continue
            visual_review = self.db.get_visual_review(asset.instance_id)
            if visual_review is None or not (visual_review["families"] or "").strip():
                skipped_no_family += 1
                continue
            if visual_review["review_status"] == "reviewed":
                skipped_reviewed += 1
                continue
            review = self.db.get_review(asset.instance_id, asset)
            candidates.append((asset, review, visual_review))

        if not candidates:
            QMessageBox.information(
                self,
                "Nothing to approve",
                "No pending classifier suggestions with visual families were found in the current filter.",
            )
            return

        family_filter = self.visual_family_filter.currentText()
        reply = QMessageBox.question(
            self,
            "Approve filtered suggestions",
            (
                f"Mark {len(candidates)} currently filtered pending suggestion(s) as reviewed?\n\n"
                f"Family filter: {family_filter}\n"
                f"Skipped: reviewed={skipped_reviewed}, no family={skipped_no_family}, non-classifier={skipped_non_classifier}\n\n"
                "Use this after you inspected thumbnails and fixed the wrong ones."
            ),
        )
        if reply != QMessageBox.Yes:
            return

        for asset, review, visual_review in candidates:
            representation = review["representation"] or infer_representation(
                asset.relative_path,
                review["asset_type"],
                asset.asset_role,
                asset.image_scope,
            )
            self.db.save_review(
                asset.instance_id,
                review["vision_domain"] or asset.vision_domain or "ads",
                review["asset_type"] or scope_to_asset_type(asset.image_scope, asset.asset_role),
                representation or "unknown",
                None,
                review["label"] or "positive",
                "uncertain",
                review["sample_role"] or default_sample_role(review["asset_type"], asset.image_scope, representation),
                review["sub_role"] or "",
                "reviewed",
                bool(review["has_no_target"]),
                review["note"] or "",
            )
            self.db.save_visual_review(
                asset.instance_id,
                (visual_review["families"] or "").split("|"),
                "reviewed",
                visual_review["note"] or review["note"] or "",
            )

        QMessageBox.information(self, "Approved", f"Approved {len(candidates)} filtered suggestion(s).")
        self.apply_filters()

    def load_asset_by_index(self, index: int) -> None:
        if index < 0 or index >= len(self.assets):
            return
        self.current_index = index
        self.current_asset = self.assets[index]
        asset = self.current_asset
        self.loading_ui = True
        ok = self.image_view.load_image(asset.original_path)
        self.path_label.setText(f"{asset.relative_path}\n{asset.width}x{asset.height}")
        self.technical_label.setText(f"{asset.instance_id}\n{asset.content_id}\n{asset.original_path}")
        duplicate_count = self.db.content_duplicate_count(asset.content_id, asset.instance_id)
        self.duplicate_label.setText(f"Same content in other files: {duplicate_count}")
        self.update_suspect_panel(asset)
        review = self.db.get_review(asset.instance_id, asset)
        self.current_asset_type = review["asset_type"]
        review = self.apply_sticky_review_state_if_needed(asset, review)
        self.current_asset_type = review["asset_type"]
        self.review_domain_panel.set_value(review["vision_domain"] or asset.vision_domain or "ads")
        self.refresh_sub_role_options(review["sub_role"] if "sub_role" in review.keys() else "")
        self.update_sub_role_visibility()
        self.asset_type_label.setText(f"Asset type (自動): {self.current_asset_type}")
        self.representation_panel.set_value(review["representation"])
        visual_review = self.db.get_visual_review(asset.instance_id)
        self.visual_family_panel.set_values(visual_review["families"] if visual_review is not None else "")
        self.sample_role_panel.set_value(
            review["sample_role"]
            or default_sample_role(self.current_asset_type, asset.image_scope, review["representation"])
        )
        self.screen_state_panel.set_value(review["screen_state"] or default_screen_state(self.current_asset_type, asset.image_scope))
        self.image_note.setPlainText(review["note"])
        self.configure_workflow(asset, review)
        self.loading_ui = False
        if not ok:
            QMessageBox.warning(self, "Image load failed", asset.original_path)
        self.load_bboxes()
        self.apply_default_bbox_source()

    def load_asset_direct(self, asset: Asset) -> None:
        self.current_index = -1
        self.current_asset = asset
        self.loading_ui = True
        ok = self.image_view.load_image(asset.original_path)
        self.path_label.setText(f"{asset.relative_path}\n{asset.width}x{asset.height}")
        self.technical_label.setText(f"{asset.instance_id}\n{asset.content_id}\n{asset.original_path}")
        duplicate_count = self.db.content_duplicate_count(asset.content_id, asset.instance_id)
        self.duplicate_label.setText(f"Same content in other files: {duplicate_count}")
        self.update_suspect_panel(asset)
        review = self.db.get_review(asset.instance_id, asset)
        self.current_asset_type = review["asset_type"]
        self.review_domain_panel.set_value(review["vision_domain"] or asset.vision_domain or "ads")
        self.refresh_sub_role_options(review["sub_role"] if "sub_role" in review.keys() else "")
        self.update_sub_role_visibility()
        self.asset_type_label.setText(f"Asset type (?芸?): {self.current_asset_type}")
        self.representation_panel.set_value(review["representation"])
        visual_review = self.db.get_visual_review(asset.instance_id)
        self.visual_family_panel.set_values(visual_review["families"] if visual_review is not None else "")
        self.sample_role_panel.set_value(
            review["sample_role"]
            or default_sample_role(self.current_asset_type, asset.image_scope, review["representation"])
        )
        self.screen_state_panel.set_value(review["screen_state"] or default_screen_state(self.current_asset_type, asset.image_scope))
        self.image_note.setPlainText(review["note"])
        self.configure_workflow(asset, review)
        self.loading_ui = False
        if not ok:
            QMessageBox.warning(self, "Image load failed", asset.original_path)
        self.load_bboxes()
        self.apply_default_bbox_source()

    def remember_saved_asset(self, asset: Asset) -> None:
        if not self.saved_asset_history or self.saved_asset_history[-1].instance_id != asset.instance_id:
            self.saved_asset_history.append(asset)
        self.saved_history_cursor = len(self.saved_asset_history)
        self.prev_saved_btn.setEnabled(bool(self.saved_asset_history))

    def previous_saved_asset(self) -> None:
        if not self.saved_asset_history:
            return
        self.saved_history_cursor = min(self.saved_history_cursor, len(self.saved_asset_history))
        if self.saved_history_cursor <= 0:
            return
        self.saved_history_cursor -= 1
        self.load_asset_direct(self.saved_asset_history[self.saved_history_cursor])
        self.prev_saved_btn.setEnabled(self.saved_history_cursor > 0)

    def update_suspect_panel(self, asset: Asset) -> None:
        records = self.suspect_records_by_instance.get(asset.instance_id, [])
        if not records:
            self.suspect_box.setVisible(False)
            self.suspect_label.setText("")
            return
        lines = []
        for i, record in enumerate(records, start=1):
            reason = record.get("suspect_reason", "")
            annotation = record.get("current_annotation", "")
            check = record.get("suggested_check", "")
            model = record.get("model_run", "")
            lines.append(f"{i}. {reason}")
            if annotation:
                lines.append(f"   Current: {annotation}")
            if check:
                lines.append(f"   Check: {check}")
            if model:
                lines.append(f"   Model: {model}")
        self.suspect_label.setText("\n".join(lines))
        self.suspect_box.setVisible(True)

    def is_classifier_workflow(self, asset: Asset | None = None) -> bool:
        if self.detector_review_mode:
            return False
        asset = asset or self.current_asset
        if asset is None:
            return False
        asset_type = getattr(self, "current_asset_type", scope_to_asset_type(asset.image_scope, asset.asset_role))
        return asset_type in {"crop", "template"} or asset.image_scope == "crop" or asset.asset_role == "template"

    def configure_workflow(self, asset: Asset, review: sqlite3.Row) -> None:
        if self.is_classifier_workflow(asset):
            self.workflow_hint.setText("Classifier 樣本：請選「要點擊目標」或「干擾樣本」。參考/錨點不會進二分類訓練，不需要畫框。")
            self.classifier_box.setVisible(True)
            self.screen_box.setVisible(False)
            self.detector_box.setVisible(False)
            self.bbox_box.setVisible(False)
            self.workflow_hint.setText("Crop/template：請勾選符合的 visual family；不確定就勾 Uncertain 或按 Postpone。")
        else:
            self.workflow_hint.setText("Detector 標註：找出畫面上所有可能需要進一步判斷的可點標記。")
            self.classifier_box.setVisible(False)
            self.screen_box.setVisible(True)
            self.detector_box.setVisible(self.screen_state_panel.value() == "actionable")
            self.bbox_box.setVisible(False)
            self.workflow_hint.setText("選「有候選標記」後，確認或框出所有可能的點擊候選。沒有就選「沒有候選標記」。")

    def current_image_domain(self) -> str:
        if self.detector_review_mode:
            return "ads"
        return self.review_domain_panel.value() or "ads"

    def current_sub_role(self) -> str:
        domain = self.current_image_domain()
        if domain not in {"game", "shared"}:
            return ""
        quick_value = self.sub_role_quick_panel.value()
        if quick_value in {"play", "got", "free"}:
            return quick_value
        custom = self.sub_role_combo.currentText().strip()
        return custom or "other"

    def refresh_sub_role_options(self, selected: str = "") -> None:
        domain = self.current_image_domain()
        current = selected.strip() if selected is not None else self.sub_role_combo.currentText().strip()
        quick_value = current if current in {"play", "got", "free"} else "other"
        self.sub_role_quick_panel.set_value(quick_value)
        self.sub_role_combo.blockSignals(True)
        self.sub_role_combo.clear()
        self.sub_role_combo.addItem("")
        values = ["other"]
        for value in self.db.sub_roles(domain):
            if value and value not in values:
                values.append(value)
        for value in values:
            self.sub_role_combo.addItem(value)
        if current and current not in {"play", "got", "free"}:
            index = self.sub_role_combo.findText(current)
            if index < 0:
                self.sub_role_combo.addItem(current)
                index = self.sub_role_combo.findText(current)
            self.sub_role_combo.setCurrentIndex(index)
        else:
            self.sub_role_combo.setCurrentIndex(0)
        self.sub_role_combo.blockSignals(False)
        self.sub_role_combo.setEnabled(quick_value == "other")

    def on_sub_role_quick_changed(self) -> None:
        quick_value = self.sub_role_quick_panel.value()
        self.sub_role_combo.setEnabled(quick_value == "other")
        if quick_value in {"play", "got", "free"}:
            self.sub_role_combo.blockSignals(True)
            self.sub_role_combo.setCurrentIndex(0)
            self.sub_role_combo.blockSignals(False)
        self.autosave_review()

    def update_sub_role_visibility(self) -> None:
        if self.detector_review_mode:
            self.sub_role_box.setVisible(False)
            return
        self.sub_role_box.setVisible(self.current_image_domain() in {"game", "shared"})

    def capture_sticky_review_state(self) -> None:
        if self.current_asset is None:
            return
        bbox_rows = self.db.bboxes(self.current_asset.instance_id)
        self.sticky_review_state = {
            "source_width": self.current_asset.width,
            "source_height": self.current_asset.height,
            "domain": self.current_image_domain(),
            "sub_role": self.current_sub_role(),
            "representation": self.representation_panel.value(),
            "screen_state": self.screen_state_panel.value(),
            "sample_role": self.sample_role_panel.value(),
            "visual_families": self.visual_family_panel.values(),
            "note": self.image_note.toPlainText(),
            "bboxes": [
                {
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "w": float(row["w"]),
                    "h": float(row["h"]),
                    "note": row["note"] or "",
                }
                for row in bbox_rows
            ],
        }

    def apply_sticky_review_state_if_needed(self, asset: Asset, review: sqlite3.Row) -> sqlite3.Row:
        if not self.apply_sticky_on_next_load or not self.sticky_review_state:
            return review
        self.apply_sticky_on_next_load = False
        if self.detector_review_mode and (self.bbox_source_panel.value() or "model") != "previous":
            return review

        state = self.sticky_review_state
        if self.is_classifier_workflow(asset):
            visual_review = self.db.get_visual_review(asset.instance_id)
            if visual_review is None or (visual_review["review_status"] != "reviewed" and not visual_review["families"]):
                self.db.save_visual_review(
                    asset.instance_id,
                    list(state.get("visual_families", [])),
                    "pending",
                    state.get("note", "") or review["note"] or "",
                )

        if review["review_status"] != "pending":
            return self.db.get_review(asset.instance_id, asset)

        domain = state["domain"] if state["domain"] in DOMAINS else review["vision_domain"]
        representation = state["representation"] or review["representation"]
        screen_state = state["screen_state"] or review["screen_state"]
        sample_role = state["sample_role"] or review["sample_role"]
        sub_role = state["sub_role"] if domain in {"game", "shared"} else ""
        note = state["note"] or review["note"]

        self.db.save_review(
            asset.instance_id,
            domain,
            review["asset_type"],
            representation,
            None,
            "positive",
            screen_state if not self.is_classifier_workflow(asset) else "uncertain",
            sample_role if self.is_classifier_workflow(asset) else "uncertain",
            sub_role,
            "pending",
            False,
            note,
        )
        if self.is_classifier_workflow(asset):
            visual_review = self.db.get_visual_review(asset.instance_id)
            if visual_review is None or not visual_review["families"]:
                self.db.save_visual_review(
                    asset.instance_id,
                    list(state.get("visual_families", [])),
                    "pending",
                    note,
                )

        existing_bboxes = self.db.bboxes(asset.instance_id)
        if not existing_bboxes and not self.is_classifier_workflow(asset):
            source_width = max(1, int(state.get("source_width") or asset.width or 1))
            source_height = max(1, int(state.get("source_height") or asset.height or 1))
            scale_x = (asset.width or source_width) / source_width
            scale_y = (asset.height or source_height) / source_height
            for bbox in state.get("bboxes", []):
                rect = QRectF(
                    float(bbox["x"]) * scale_x,
                    float(bbox["y"]) * scale_y,
                    max(1.0, float(bbox["w"]) * scale_x),
                    max(1.0, float(bbox["h"]) * scale_y),
                )
                self.db.create_bbox(asset, rect, domain, bbox.get("note", ""))

        return self.db.get_review(asset.instance_id, asset)

    def load_bboxes(self) -> None:
        self.bbox_items.clear()
        for row in self.db.bboxes(self.current_asset.instance_id if self.current_asset else ""):
            rect = QRectF(float(row["x"]), float(row["y"]), float(row["w"]), float(row["h"]))
            item = BBoxItem(int(row["id"]), rect, self)
            self.image_view.scene.addItem(item)
            self.bbox_items[item.bbox_id] = item
        self.selected_bbox_id = None
        self.clear_bbox_ui()
        self.bbox_box.setVisible(False)
        self.update_workflow_hint()

    def current_model_proposals(self) -> list[DetectorProposal]:
        if self.current_asset is None:
            return []
        keys = {
            self.path_key(self.current_asset.original_path),
            self.path_key(self.current_asset.relative_path),
        }
        proposals: list[DetectorProposal] = []
        seen: set[tuple[float, float, float, float, str]] = set()
        for key in keys:
            for proposal in self.detector_proposals_by_path.get(key, []):
                dedupe_key = (proposal.x, proposal.y, proposal.w, proposal.h, proposal.candidate_id)
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    proposals.append(proposal)
        proposals.sort(key=lambda item: item.score, reverse=True)
        return proposals

    def current_click_bboxes(self) -> list[DetectorProposal]:
        if self.current_asset is None:
            return []
        keys = {
            self.path_key(self.current_asset.original_path),
            self.path_key(self.current_asset.relative_path),
        }
        proposals: list[DetectorProposal] = []
        seen: set[tuple[float, float, float, float, str]] = set()
        for key in keys:
            for proposal in self.click_bboxes_by_path.get(key, []):
                dedupe_key = (proposal.x, proposal.y, proposal.w, proposal.h, proposal.candidate_id)
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    proposals.append(proposal)
        proposals.sort(key=lambda item: item.candidate_id)
        return proposals

    def proposal_note(self, proposal: DetectorProposal) -> str:
        parts = ["model_detect"]
        if proposal.candidate_id:
            parts.append(proposal.candidate_id)
        if proposal.source:
            parts.append(proposal.source)
        if proposal.score:
            parts.append(f"score={proposal.score}")
        return " | ".join(parts)

    def click_note(self, proposal: DetectorProposal) -> str:
        parts = ["click_success"]
        if proposal.candidate_id:
            parts.append(proposal.candidate_id)
        if proposal.source:
            parts.append(proposal.source)
        if proposal.score:
            parts.append(f"change={proposal.score}")
        return " | ".join(parts)

    def add_bbox_record_and_item(self, rect: QRectF, note: str = "") -> int:
        if self.current_asset is None:
            raise RuntimeError("No current asset")
        bbox_id = self.db.create_bbox(self.current_asset, rect, "ads", note)
        item = BBoxItem(bbox_id, rect, self)
        self.image_view.scene.addItem(item)
        self.bbox_items[bbox_id] = item
        return bbox_id

    def clear_current_bboxes(self) -> None:
        if self.current_asset is None:
            return
        for item in list(self.bbox_items.values()):
            self.image_view.scene.removeItem(item)
        self.bbox_items.clear()
        self.selected_bbox_id = None
        self.db.delete_bboxes_for_instance(self.current_asset.instance_id)
        self.clear_bbox_ui()
        self.bbox_box.setVisible(False)

    def set_detector_screen_actionable(self) -> None:
        self.screen_state_panel.set_value("actionable")
        self.detector_box.setVisible(True)
        self.autosave_review()

    def apply_proposals_to_current(
        self,
        proposals: list[DetectorProposal],
        *,
        label: str,
        note_builder,
        replace: bool = True,
        silent: bool = False,
    ) -> None:
        if self.current_asset is None or self.is_classifier_workflow():
            return
        if not proposals:
            self.update_proposal_count_label()
            if not silent:
                QMessageBox.information(self, f"No {label} boxes", f"No {label} boxes were found for this image.")
            return
        if replace:
            self.clear_current_bboxes()
        self.set_detector_screen_actionable()
        last_bbox_id: int | None = None
        for proposal in proposals:
            x = min(max(0.0, proposal.x), max(0.0, float(self.current_asset.width - 1)))
            y = min(max(0.0, proposal.y), max(0.0, float(self.current_asset.height - 1)))
            w = min(max(1.0, proposal.w), max(1.0, float(self.current_asset.width) - x))
            h = min(max(1.0, proposal.h), max(1.0, float(self.current_asset.height) - y))
            last_bbox_id = self.add_bbox_record_and_item(QRectF(x, y, w, h), note_builder(proposal))
        if last_bbox_id is not None:
            self.select_bbox(last_bbox_id)
        self.proposal_count_label.setText(f"{label} boxes: {len(proposals)}")
        self.update_progress()
        self.update_workflow_hint()

    def apply_model_proposals_to_current(self, replace: bool = True, silent: bool = False) -> None:
        self.apply_proposals_to_current(
            self.current_model_proposals(),
            label="Model",
            note_builder=self.proposal_note,
            replace=replace,
            silent=silent,
        )

    def apply_click_bboxes_to_current(self, replace: bool = True, silent: bool = False) -> None:
        self.apply_proposals_to_current(
            self.current_click_bboxes(),
            label="Click",
            note_builder=self.click_note,
            replace=replace,
            silent=silent,
        )

    def apply_previous_bboxes_to_current(self, replace: bool = True, silent: bool = False) -> None:
        if self.current_asset is None or self.is_classifier_workflow():
            return
        state = self.sticky_review_state or {}
        previous_boxes = state.get("bboxes", [])
        if not previous_boxes:
            if not silent:
                QMessageBox.information(self, "No previous boxes", "No previous saved bbox selection is available yet.")
            self.update_proposal_count_label()
            return
        if replace:
            self.clear_current_bboxes()
        self.set_detector_screen_actionable()
        source_width = max(1, int(state.get("source_width") or self.current_asset.width or 1))
        source_height = max(1, int(state.get("source_height") or self.current_asset.height or 1))
        scale_x = (self.current_asset.width or source_width) / source_width
        scale_y = (self.current_asset.height or source_height) / source_height
        last_bbox_id: int | None = None
        for bbox in previous_boxes:
            rect = QRectF(
                float(bbox["x"]) * scale_x,
                float(bbox["y"]) * scale_y,
                max(1.0, float(bbox["w"]) * scale_x),
                max(1.0, float(bbox["h"]) * scale_y),
            )
            last_bbox_id = self.add_bbox_record_and_item(rect, bbox.get("note", ""))
        if last_bbox_id is not None:
            self.select_bbox(last_bbox_id)
        self.update_progress()
        self.update_workflow_hint()

    def apply_default_bbox_source(self) -> None:
        if self.loading_ui or self.current_asset is None or self.is_classifier_workflow() or self.bbox_items:
            self.update_proposal_count_label()
            return
        source = self.bbox_source_panel.value() or "model"
        if source == "model":
            self.apply_model_proposals_to_current(replace=False, silent=True)
        elif source == "click":
            self.apply_click_bboxes_to_current(replace=False, silent=True)
        elif source == "previous":
            self.apply_previous_bboxes_to_current(replace=False, silent=True)
        self.update_proposal_count_label()

    def on_bbox_source_changed(self) -> None:
        if self.loading_ui or self.current_asset is None or self.is_classifier_workflow():
            return
        source = self.bbox_source_panel.value() or "model"
        if source == "model":
            self.apply_model_proposals_to_current(replace=True, silent=True)
        elif source == "click":
            self.apply_click_bboxes_to_current(replace=True, silent=True)
        elif source == "previous":
            self.apply_previous_bboxes_to_current(replace=True, silent=True)
        else:
            self.update_proposal_count_label()

    def update_proposal_count_label(self) -> None:
        if not hasattr(self, "proposal_count_label"):
            return
        model_count = len(self.current_model_proposals())
        click_count = len(self.current_click_bboxes())
        self.proposal_count_label.setText(f"Model boxes: {model_count} | Click boxes: {click_count}")

    def clear_bbox_ui(self) -> None:
        self.loading_ui = True
        self.bbox_domain_auto.setText("Domain: ads (auto)")
        self.bbox_class_auto.setText("BBox class: visual_candidate (auto)")
        for spin in [self.bbox_x, self.bbox_y, self.bbox_w, self.bbox_h]:
            spin.setValue(0)
        self.bbox_note.setPlainText("")
        self.loading_ui = False

    def autosave_review(self) -> None:
        if self.loading_ui or self.current_asset is None:
            return
        row = self.db.conn.execute(
            "SELECT review_status FROM image_reviews WHERE instance_id = ?",
            (self.current_asset.instance_id,),
        ).fetchone()
        status = row["review_status"] if row is not None else "pending"
        self.db.save_review(
            self.current_asset.instance_id,
            self.current_image_domain(),
            self.current_asset_type,
            self.representation_panel.value(),
            None,
            "positive",
            self.screen_state_panel.value() if not self.is_classifier_workflow() else "uncertain",
            "uncertain",
            self.current_sub_role(),
            status,
            False,
            self.image_note.toPlainText(),
        )
        self.update_workflow_hint()
        self.update_progress()

    def autosave_visual_family(self) -> None:
        if self.loading_ui or self.current_asset is None or not self.is_classifier_workflow():
            return
        row = self.db.get_visual_review(self.current_asset.instance_id)
        status = row["review_status"] if row is not None else "pending"
        if status == "reviewed":
            status = "pending"
        self.db.save_visual_review(
            self.current_asset.instance_id,
            self.visual_family_panel.values(),
            status,
            self.image_note.toPlainText(),
        )
        self.update_workflow_hint()
        self.update_progress()

    def save_review_status(self, status: str) -> None:
        if self.current_asset is None:
            return
        if status == "reviewed" and self.is_classifier_workflow() and not self.visual_family_panel.values():
            QMessageBox.warning(self, "Missing visual family", "請至少勾選一個 visual family，或按 Postpone 稍後處理。")
            return
        if status == "reviewed":
            self.capture_sticky_review_state()
            self.apply_sticky_on_next_load = True
        self.db.save_review(
            self.current_asset.instance_id,
            self.current_image_domain(),
            self.current_asset_type,
            self.representation_panel.value(),
            None,
            "positive",
            self.screen_state_panel.value() if not self.is_classifier_workflow() else "uncertain",
            "uncertain",
            self.current_sub_role(),
            status,
            False,
            self.image_note.toPlainText(),
        )
        if self.is_classifier_workflow():
            self.db.save_visual_review(
                self.current_asset.instance_id,
                self.visual_family_panel.values(),
                status,
                self.image_note.toPlainText(),
            )
        if status == "reviewed":
            self.remember_saved_asset(self.current_asset)
        self.update_progress()
        if status == "reviewed":
            if self.review_filter.currentText() in {"unreviewed", "pending", "pending instance"} or self.visual_review_filter.currentText() == "unreviewed":
                self.remove_current_from_unreviewed_list()
                return
            self.next_image()

    def update_progress(self) -> None:
        counts = self.db.counts()
        self.progress_label.setText(
            f"Filtered {len(self.assets)} | image reviewed {counts['reviews']} | image pending {counts['pending']} | "
            f"visual reviewed {counts['visual_reviews']} | visual pending {counts['visual_pending']} | bbox {counts['bboxes']}"
        )

    def update_workflow_hint(self) -> None:
        if self.current_asset is None:
            return
        if self.is_classifier_workflow():
            if self.sample_role_panel.value() == "uncertain":
                self.workflow_hint.setText("Classifier 樣本：請確認樣本用途。")
            else:
                self.workflow_hint.setText("已完成，可以儲存並下一張。")
        else:
            state = self.screen_state_panel.value()
            if state == "actionable" and not self.bbox_items:
                self.workflow_hint.setText("有可點目標：請新增一個或多個候選框。")
            elif state in {"waiting", "returned_to_game"}:
                self.workflow_hint.setText("已完成，可以儲存並下一張。")
            elif self.selected_bbox_id is None:
                self.workflow_hint.setText("Detector 畫面：可再新增候選框，或儲存並下一張。")
            else:
                self.workflow_hint.setText("已完成，可以儲存並下一張。")

    def on_screen_state_changed(self) -> None:
        state = self.screen_state_panel.value()
        self.detector_box.setVisible(not self.is_classifier_workflow() and state == "actionable")
        if state != "actionable":
            self.bbox_box.setVisible(False)
        self.autosave_review()

    def on_domain_changed(self) -> None:
        self.refresh_sub_role_options()
        self.update_sub_role_visibility()
        self.clear_bbox_ui()
        self.autosave_review()

    def update_progress(self) -> None:
        counts = self.db.counts()
        self.progress_label.setText(
            f"目前清單 {len(self.assets)} | 已審查 {counts['reviews']} | 待處理 {counts['pending']} | 候選框 {counts['bboxes']}"
        )

    def update_workflow_hint(self) -> None:
        if self.current_asset is None:
            return
        if self.is_classifier_workflow():
            if not self.visual_family_panel.values():
                self.workflow_hint.setText("Crop/template：請勾選至少一個 visual family；不確定就勾 Uncertain。")
            else:
                self.workflow_hint.setText("已選 visual family，可以 Save & Next。")
            return

        state = self.screen_state_panel.value()
        if state == "actionable" and not self.bbox_items:
            self.workflow_hint.setText("有候選標記：請套用模型框、沿用上一張，或手動畫出所有候選框。")
        elif state in {"waiting", "returned_to_game"}:
            self.workflow_hint.setText("此畫面不需要 bbox，可以 Save & Next。")
        elif self.selected_bbox_id is None:
            self.workflow_hint.setText("已建立候選框，可以繼續框下一個或 Save & Next。")
        else:
            self.workflow_hint.setText("正在編輯 bbox；完成後可 Save & Next。")

    def start_bbox(self) -> None:
        if self.current_asset is None:
            return
        self.image_view.start_bbox_mode()

    def toggle_advanced(self, visible: bool) -> None:
        self.advanced_box.setVisible(visible)
        self.advanced_btn.setText("隱藏進階座標" if visible else "顯示進階座標")

    def toggle_image_details(self, visible: bool) -> None:
        self.advanced_image_box.setVisible(visible)
        self.advanced_image_btn.setText("隱藏進階資訊" if visible else "顯示進階資訊")

    def create_bbox_from_rect(self, rect: QRectF) -> None:
        if self.current_asset is None:
            return
        self.set_detector_screen_actionable()
        bbox_id = self.add_bbox_record_and_item(rect)
        item = self.bbox_items[bbox_id]
        item.setSelected(True)
        self.select_bbox(bbox_id)
        self.update_workflow_hint()

    def save_bbox_item_rect(self, item: BBoxItem) -> None:
        if self.loading_ui:
            return
        self.db.update_bbox_rect(item.bbox_id, item.image_rect())
        if self.selected_bbox_id == item.bbox_id:
            self.select_bbox(item.bbox_id)

    def select_bbox(self, bbox_id: int) -> None:
        row = self.db.conn.execute("SELECT * FROM bboxes WHERE id = ?", (bbox_id,)).fetchone()
        if row is None:
            return
        self.selected_bbox_id = bbox_id
        self.loading_ui = True
        domain = "ads"
        action_class_id = self.db.visual_candidate_class_id()
        if row["vision_domain"] != domain or row["class_id"] != action_class_id or row["label"] != "positive":
            self.db.update_bbox_metadata(bbox_id, domain, action_class_id, "positive", row["note"])
            row = self.db.conn.execute("SELECT * FROM bboxes WHERE id = ?", (bbox_id,)).fetchone()
        self.bbox_domain_auto.setText("Domain: ads (auto)")
        self.bbox_class_auto.setText("BBox class: visual_candidate (auto)")
        self.bbox_x.setValue(float(row["x"]))
        self.bbox_y.setValue(float(row["y"]))
        self.bbox_w.setValue(float(row["w"]))
        self.bbox_h.setValue(float(row["h"]))
        self.bbox_note.setPlainText(row["note"])
        self.bbox_box.setVisible(True)
        self.loading_ui = False
        self.update_workflow_hint()

    def autosave_bbox_rect_from_spin(self) -> None:
        if self.loading_ui or self.selected_bbox_id is None:
            return
        rect = QRectF(self.bbox_x.value(), self.bbox_y.value(), max(1.0, self.bbox_w.value()), max(1.0, self.bbox_h.value()))
        self.db.update_bbox_rect(self.selected_bbox_id, rect)
        item = self.bbox_items.get(self.selected_bbox_id)
        if item is not None:
            item.setPos(0, 0)
            item.setRect(rect)

    def autosave_bbox_metadata(self) -> None:
        if self.loading_ui or self.selected_bbox_id is None:
            return
        self.db.update_bbox_metadata(
            self.selected_bbox_id,
            "ads",
            self.db.visual_candidate_class_id(),
            "positive",
            self.bbox_note.toPlainText(),
        )
        self.update_workflow_hint()

    def delete_selected_bbox(self) -> None:
        if self.selected_bbox_id is None:
            return
        bbox_id = self.selected_bbox_id
        item = self.bbox_items.pop(bbox_id, None)
        if item is not None:
            self.image_view.scene.removeItem(item)
        self.db.delete_bbox(bbox_id)
        self.selected_bbox_id = None
        self.clear_bbox_ui()
        self.bbox_box.setVisible(False)
        self.update_progress()
        self.update_workflow_hint()

    def prev_image(self) -> None:
        if self.current_index > 0:
            self.asset_list.setCurrentRow(self.current_index - 1)

    def next_image(self) -> None:
        if self.current_index + 1 < min(len(self.assets), self.asset_list.count()):
            self.asset_list.setCurrentRow(self.current_index + 1)

    def next_pending(self) -> None:
        start = max(0, self.current_index + 1)
        for idx in range(start, min(len(self.assets), self.asset_list.count())):
            review = self.db.conn.execute(
                "SELECT review_status FROM image_reviews WHERE instance_id = ?",
                (self.assets[idx].instance_id,),
            ).fetchone()
            if review is None or review["review_status"] == "pending":
                self.asset_list.setCurrentRow(idx)
                return

    def open_class_manager(self) -> None:
        dialog = ClassDialog(self, self.db)
        dialog.exec()
        self.refresh_class_combo()

    def export_annotations(self) -> None:
        paths = self.db.export_csv_json(self.export_dir)
        QMessageBox.information(self, "匯出完成", "\n".join(str(path) for path in paths))


def ensure_dirs(base: Path) -> tuple[Path, Path]:
    review_dir = base / "review"
    export_dir = base / "exports"
    (review_dir / "backups").mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    return review_dir, export_dir


def run_self_test(project_root: Path) -> int:
    base = project_root / "vision_platform" / "vision_assets"
    review_dir, export_dir = ensure_dirs(base)
    db = ReviewDatabase(review_dir / "vision_review.db", base / "inventory" / "assets.csv")
    counts = db.counts()
    export_paths = db.export_csv_json(export_dir)
    print(f"db={db.db_path}")
    print(f"assets={counts['assets']} reviews={counts['reviews']} pending={counts['pending']} bboxes={counts['bboxes']}")
    for path in export_paths:
        print(f"export={path}")
    db.close()
    return 0


def run_workflow_demo(project_root: Path) -> int:
    base = project_root / "vision_platform" / "vision_assets"
    review_dir, _export_dir = ensure_dirs(base)
    demo_db = review_dir / "vision_review_demo.db"
    if demo_db.exists():
        demo_db.unlink()
    db = ReviewDatabase(demo_db, base / "inventory" / "assets.csv")
    edge_row = db.conn.execute(
        """
        SELECT * FROM assets
        WHERE relative_path LIKE '%close_glyphs%edge%'
        ORDER BY relative_path
        LIMIT 1
        """
    ).fetchone()
    if edge_row is None:
        raise RuntimeError("No edge glyph template asset found")
    edge_asset = db.row_to_asset(edge_row)
    edge_review = db.get_review(edge_asset.instance_id, edge_asset)
    db.save_review(
        edge_asset.instance_id,
        "ads",
        edge_review["asset_type"],
        edge_review["representation"],
        None,
        "positive",
        "uncertain",
        "reference_only",
        "",
        "reviewed",
        False,
        "workflow demo: edge glyph reference_only without bbox",
    )

    raw_template_row = db.conn.execute(
        """
        SELECT * FROM assets
        WHERE vision_domain = 'ads'
          AND asset_role = 'template'
          AND image_scope = 'crop'
          AND relative_path LIKE '%free_ad%'
        ORDER BY relative_path
        LIMIT 1
        """
    ).fetchone()
    if raw_template_row is None:
        raw_template_row = db.conn.execute(
            """
            SELECT * FROM assets
            WHERE vision_domain = 'ads'
              AND asset_role = 'template'
              AND image_scope = 'crop'
            ORDER BY relative_path
            LIMIT 1
            """
        ).fetchone()
    raw_asset = db.row_to_asset(raw_template_row)
    raw_review = db.get_review(raw_asset.instance_id, raw_asset)
    db.save_review(
        raw_asset.instance_id,
        "ads",
        raw_review["asset_type"],
        "raw",
        None,
        "positive",
        "uncertain",
        "action_target",
        "",
        "reviewed",
        False,
        "workflow demo: raw template action_target without bbox",
    )

    fullscreen_row = db.conn.execute(
        """
        SELECT * FROM assets
        WHERE image_scope = 'fullscreen'
          AND vision_domain = 'ads'
          AND source_root = 'ads2\\assets\\3_reference_screens'
        ORDER BY relative_path
        LIMIT 1
        """
    ).fetchone()
    if fullscreen_row is None:
        raise RuntimeError("No ads fullscreen asset found")
    fullscreen_asset = db.row_to_asset(fullscreen_row)
    fullscreen_review = db.get_review(fullscreen_asset.instance_id, fullscreen_asset)
    rect = QRectF(10, 10, min(120, max(10, fullscreen_asset.width - 20)), min(80, max(10, fullscreen_asset.height - 20)))
    bbox_id = db.create_bbox(fullscreen_asset, rect, "ads")
    db.update_bbox_metadata(bbox_id, "ads", db.action_target_class_id(), "positive", "workflow demo: ads actionable bbox")
    db.save_review(
        fullscreen_asset.instance_id,
        "ads",
        fullscreen_review["asset_type"],
        fullscreen_review["representation"],
        None,
        "positive",
        "actionable",
        "uncertain",
        "",
        "reviewed",
        False,
        "workflow demo: ads actionable fullscreen with bbox",
    )

    returned_row = db.conn.execute(
        """
        SELECT * FROM assets
        WHERE image_scope = 'fullscreen'
        ORDER BY relative_path
        LIMIT 1
        """
    ).fetchone()
    if returned_row is None:
        raise RuntimeError("No fullscreen asset found")
    returned_asset = db.row_to_asset(returned_row)
    returned_review = db.get_review(returned_asset.instance_id, returned_asset)
    db.save_review(
        returned_asset.instance_id,
        "ads",
        returned_review["asset_type"],
        returned_review["representation"],
        None,
        "positive",
        "returned_to_game",
        "uncertain",
        "",
        "reviewed",
        False,
        "workflow demo: returned to game without bbox",
    )

    edge_result = db.conn.execute(
        """
        SELECT r.*
        FROM image_reviews r
        WHERE r.instance_id = ?
        """,
        (edge_asset.instance_id,),
    ).fetchone()
    bbox_result = db.conn.execute(
        """
        SELECT b.*, c.name AS class_name
        FROM bboxes b LEFT JOIN classes c ON c.id = b.class_id
        WHERE b.id = ?
        """,
        (bbox_id,),
    ).fetchone()
    print(f"demo_db={demo_db}")
    print(
        "edge_glyph_template:",
        edge_asset.relative_path,
        f"asset_type={edge_result['asset_type']}",
        f"representation={edge_result['representation']}",
        f"sample_role={edge_result['sample_role']}",
        f"bbox_count={db.conn.execute('SELECT COUNT(*) FROM bboxes WHERE instance_id=?', (edge_asset.instance_id,)).fetchone()[0]}",
    )
    raw_result = db.conn.execute(
        "SELECT * FROM image_reviews WHERE instance_id = ?",
        (raw_asset.instance_id,),
    ).fetchone()
    print(
        "raw_template:",
        raw_asset.relative_path,
        f"asset_type={raw_result['asset_type']}",
        f"representation={raw_result['representation']}",
        f"sample_role={raw_result['sample_role']}",
        f"bbox_count={db.conn.execute('SELECT COUNT(*) FROM bboxes WHERE instance_id=?', (raw_asset.instance_id,)).fetchone()[0]}",
    )
    print(
        "fullscreen_detector:",
        fullscreen_asset.relative_path,
        f"bbox=({bbox_result['x']},{bbox_result['y']},{bbox_result['w']},{bbox_result['h']})",
        f"domain={bbox_result['vision_domain']}",
        f"class={bbox_result['class_name']}",
        f"label={bbox_result['label']}",
    )
    returned_result = db.conn.execute(
        "SELECT * FROM image_reviews WHERE instance_id = ?",
        (returned_asset.instance_id,),
    ).fetchone()
    print(
        "returned_to_game_screen:",
        returned_asset.relative_path,
        f"screen_state={returned_result['screen_state']}",
        f"bbox_count={db.conn.execute('SELECT COUNT(*) FROM bboxes WHERE instance_id=?', (returned_asset.instance_id,)).fetchone()[0]}",
    )
    db.close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ads Vision Review GUI")
    parser.add_argument("--project-root", default=str(project_root_from_file()))
    parser.add_argument("--config", default="", help="Optional GUI config JSON. Defaults to vision_platform/vision_assets/review_gui_config.json.")
    parser.add_argument("--self-test", action="store_true", help="Initialize DB and export annotations without opening GUI.")
    parser.add_argument("--smoke-gui", action="store_true", help="Open the GUI briefly and exit automatically.")
    parser.add_argument("--smoke-size", default="", help="Resize smoke GUI window, for example 1366x768.")
    parser.add_argument("--smoke-expand-advanced", action="store_true", help="Expand advanced panels during smoke GUI validation.")
    parser.add_argument("--smoke-check-layout", action="store_true", help="Fail smoke GUI if fixed action buttons are outside the window.")
    parser.add_argument("--workflow-demo", action="store_true", help="Run classifier and detector workflow demos in a separate demo DB.")
    return parser.parse_args()


def load_gui_config(project_root: Path, config_arg: str) -> dict[str, Any]:
    config_path = Path(config_arg) if config_arg else project_root / "vision_platform" / "vision_assets" / "review_gui_config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Cannot read GUI config {config_path}: {exc}") from exc


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    base = project_root / "vision_platform" / "vision_assets"
    gui_config = load_gui_config(project_root, args.config)
    review_dir, export_dir = ensure_dirs(base)
    db = ReviewDatabase(review_dir / "vision_review.db", base / "inventory" / "assets.csv")
    if args.self_test:
        counts = db.counts()
        export_paths = db.export_csv_json(export_dir)
        print(f"db={db.db_path}")
        print(f"assets={counts['assets']} reviews={counts['reviews']} pending={counts['pending']} bboxes={counts['bboxes']}")
        for path in export_paths:
            print(f"export={path}")
        db.close()
        return 0
    if args.workflow_demo:
        db.close()
        return run_workflow_demo(project_root)

    app = QApplication(sys.argv)
    window = MainWindow(db, export_dir, gui_config)
    if args.smoke_size:
        try:
            width_text, height_text = args.smoke_size.lower().split("x", 1)
            window.resize(int(width_text), int(height_text))
        except ValueError:
            db.close()
            raise SystemExit(f"Invalid --smoke-size value: {args.smoke_size}")
    window.show()
    if args.smoke_gui:
        def run_smoke_checks() -> None:
            if args.smoke_expand_advanced:
                window.advanced_image_btn.setChecked(True)
                window.toggle_image_details(True)
                window.advanced_btn.setChecked(True)
                window.toggle_advanced(True)
            if args.smoke_check_layout:
                app.processEvents()
                failures = []
                for name, button in [("Save and Next", window.save_next_btn), ("Postpone", window.postpone_btn)]:
                    top_left = button.mapTo(window, button.rect().topLeft())
                    bottom = top_left.y() + button.height()
                    ok = button.isVisible() and bottom <= window.height()
                    print(f"layout_check {name}: visible={button.isVisible()} bottom={bottom} window_height={window.height()} ok={ok}")
                    if not ok:
                        failures.append(name)
                app.exit(2 if failures else 0)
                return
            app.quit()

        QTimer.singleShot(500, run_smoke_checks)
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
