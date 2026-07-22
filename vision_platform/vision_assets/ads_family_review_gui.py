from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


FAMILY_OPTIONS = [
    "x_mark",
    "play_triangle",
    "google_play",
    "next",
    "free",
    "got",
    "arrow",
    "double_triangle",
    "single_chevron",
    "double_chevron",
    "double_chevron_text",
    "back_arrow",
    "next_button",
    "arrow_other",
    "negative",
    "other",
    "uncertain",
]
TRAIN_FAMILIES = {"x_mark", "play_triangle", "google_play", "next", "free", "got", "arrow"}
FAMILY_DISPLAY = {
    "x_mark": "X\nx_mark",
    "play_triangle": "▶\nplay",
    "google_play": "GP\ngoogle",
    "next": "Next\nnext",
    "free": "Free\nfree",
    "got": "Got\ngot",
    "arrow": "→\narrow",
    "double_triangle": "▶▶|\ndouble_tri",
    "single_chevron": ">\nsingle_chev",
    "double_chevron": ">>\ndouble_chev",
    "double_chevron_text": ">> Ad\nchev_text",
    "back_arrow": "←\nback",
    "next_button": "▶ Next\nnext_btn",
    "arrow_other": "?\narrow_other",
    "negative": "No\nnegative",
    "other": "Other\nother",
    "uncertain": "?\nuncertain",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4096)
def image_signature(path_text: str) -> tuple:
    try:
        with Image.open(path_text) as image:
            image = image.convert("RGB").resize((8, 8), Image.Resampling.BILINEAR)
            pixels = list(image.getdata())
    except Exception:
        return (999, path_text.lower())
    means = tuple(sum(pixel[channel] for pixel in pixels) // max(1, len(pixels)) for channel in range(3))
    brightness = sum(means) // 3
    quantized = tuple(tuple(channel // 32 for channel in pixel) for pixel in pixels)
    return (brightness // 16, means[0] // 16, means[1] // 16, means[2] // 16, quantized, path_text.lower())


def split_families(text: str | None) -> list[str]:
    if not text:
        return []
    return [item for item in text.split("|") if item]


def family_text(values: list[str]) -> str:
    return "|".join(sorted({value for value in values if value in FAMILY_OPTIONS}))


@dataclass
class FamilyAsset:
    instance_id: str
    content_id: str
    original_path: str
    relative_path: str
    filename: str
    source_root: str
    asset_role: str
    image_scope: str
    width: int
    height: int
    review_status: str
    human_families: list[str]
    suggestion_families: list[str]
    probabilities: dict[str, float]
    suggestion_source: str
    note: str

    @property
    def effective_families(self) -> list[str]:
        return self.human_families if self.review_status == "reviewed" else self.suggestion_families

    @property
    def display_status(self) -> str:
        if self.review_status == "reviewed":
            return "reviewed"
        if self.review_status == "postponed":
            return "postponed"
        return "unreviewed"

    @property
    def top_probability(self) -> float:
        if not self.probabilities:
            return 0.0
        return max(self.probabilities.values())


class ReviewStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def ensure_schema(self) -> None:
        self.conn.execute(
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
        self.conn.commit()

    def query_assets(
        self,
        *,
        status: str,
        family: str,
        search: str,
        path_contains: str,
        exclude_path_contains: list[str],
        source_root: str,
        sort_mode: str,
        instance_ids: list[str] | None = None,
    ) -> list[FamilyAsset]:
        clauses = [
            "a.scan_status = 'ok'",
            "a.vision_domain IN ('ads', 'shared')",
            "(a.image_scope = 'crop' OR a.asset_role = 'template' OR a.asset_role = 'candidate_crop' OR a.asset_role = 'runtime_collection')",
        ]
        params: list[Any] = []
        instance_order: dict[str, int] = {}
        if instance_ids:
            clean_ids = [item.strip() for item in instance_ids if item.strip()]
            if clean_ids:
                instance_order = {instance_id: index for index, instance_id in enumerate(clean_ids)}
                placeholders = ",".join("?" for _ in clean_ids)
                clauses.append(f"a.instance_id IN ({placeholders})")
                params.extend(clean_ids)
        if source_root and source_root != "all":
            clauses.append("a.source_root = ?")
            params.append(source_root)
        if path_contains:
            clauses.append("a.relative_path LIKE ?")
            params.append(f"%{path_contains}%")
        for token in exclude_path_contains:
            token = token.strip()
            if token:
                clauses.append("a.relative_path NOT LIKE ?")
                params.append(f"%{token}%")
        if search:
            clauses.append("(a.relative_path LIKE ? OR a.filename LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"""
            SELECT
                a.instance_id, a.content_id, a.original_path, a.relative_path, a.filename,
                a.source_root, a.asset_role, a.image_scope, a.width, a.height,
                COALESCE(v.review_status, 'pending') AS review_status,
                COALESCE(v.families, '') AS review_families,
                COALESCE(v.note, '') AS review_note,
                COALESCE(m.families, '') AS suggestion_families,
                COALESCE(m.probabilities_json, '{{}}') AS probabilities_json,
                COALESCE(m.model_name, '') AS suggestion_model
            FROM assets a
            LEFT JOIN visual_family_reviews v ON v.instance_id = a.instance_id
            LEFT JOIN visual_family_model_suggestions m ON m.instance_id = a.instance_id
            WHERE {where}
            ORDER BY a.relative_path COLLATE NOCASE
            """,
            params,
        ).fetchall()

        assets = [self.row_to_asset(row) for row in rows]
        if status == "unreviewed":
            assets = [asset for asset in assets if asset.display_status == "unreviewed"]
        elif status == "reviewed":
            assets = [asset for asset in assets if asset.display_status == "reviewed"]
        elif status == "postponed":
            assets = [asset for asset in assets if asset.display_status == "postponed"]
        elif status == "changed":
            assets = [
                asset
                for asset in assets
                if asset.display_status == "reviewed" and set(asset.human_families) != set(asset.suggestion_families)
            ]

        if family != "all":
            assets = [asset for asset in assets if family in asset.effective_families]

        if sort_mode == "family":
            assets.sort(key=lambda asset: ("|".join(asset.effective_families), -asset.top_probability, image_signature(asset.original_path)))
        elif sort_mode == "confidence_low":
            assets.sort(key=lambda asset: (asset.top_probability, image_signature(asset.original_path)))
        elif sort_mode == "image":
            assets.sort(key=lambda asset: image_signature(asset.original_path))
        elif sort_mode == "review_list" and instance_order:
            assets.sort(key=lambda asset: instance_order.get(asset.instance_id, 10**9))
        else:
            assets.sort(key=lambda asset: asset.relative_path.lower())
        return assets

    def row_to_asset(self, row: sqlite3.Row) -> FamilyAsset:
        review_status = row["review_status"] or "pending"
        review_families = split_families(row["review_families"])
        suggestion_source = "model"
        suggestion_families = split_families(row["suggestion_families"])
        if not suggestion_families and review_status != "reviewed" and row["review_note"].startswith("model_prefill"):
            suggestion_families = review_families
            suggestion_source = "legacy_pending_prefill"
        probabilities: dict[str, float] = {}
        try:
            raw_probs = json.loads(row["probabilities_json"] or "{}")
            probabilities = {key: float(value) for key, value in raw_probs.items()}
        except Exception:
            probabilities = {}
        return FamilyAsset(
            instance_id=row["instance_id"],
            content_id=row["content_id"],
            original_path=row["original_path"],
            relative_path=row["relative_path"],
            filename=row["filename"] or Path(row["original_path"]).name,
            source_root=row["source_root"] or "",
            asset_role=row["asset_role"] or "",
            image_scope=row["image_scope"] or "",
            width=int(row["width"] or 0),
            height=int(row["height"] or 0),
            review_status=review_status,
            human_families=review_families if review_status == "reviewed" else [],
            suggestion_families=suggestion_families,
            probabilities=probabilities,
            suggestion_source=suggestion_source if suggestion_families else "",
            note=row["review_note"] or "",
        )

    def source_roots(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT source_root
            FROM assets
            WHERE scan_status = 'ok'
              AND vision_domain IN ('ads', 'shared')
              AND (image_scope = 'crop' OR asset_role IN ('template', 'candidate_crop', 'runtime_collection'))
            ORDER BY source_root COLLATE NOCASE
            """
        ).fetchall()
        return [row[0] for row in rows if row[0]]

    def save_review(self, asset: FamilyAsset, families: list[str], status: str, note: str = "") -> None:
        now = utc_now()
        text = family_text(families)
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
            (asset.instance_id, text, status, note, now, now),
        )
        self.conn.commit()

    def counts(self) -> dict[str, int]:
        reviewed = self.conn.execute("SELECT COUNT(*) FROM visual_family_reviews WHERE review_status = 'reviewed'").fetchone()[0]
        postponed = self.conn.execute("SELECT COUNT(*) FROM visual_family_reviews WHERE review_status = 'postponed'").fetchone()[0]
        suggestions = self.conn.execute("SELECT COUNT(*) FROM visual_family_model_suggestions").fetchone()[0]
        return {"reviewed": reviewed, "postponed": postponed, "suggestions": suggestions}

    def export_reviews(self, path: Path) -> Path:
        rows = self.conn.execute(
            """
            SELECT
                a.instance_id, a.content_id, a.original_path, a.relative_path,
                v.families, v.review_status, v.note,
                m.families AS model_families, m.probabilities_json
            FROM visual_family_reviews v
            JOIN assets a ON a.instance_id = v.instance_id
            LEFT JOIN visual_family_model_suggestions m ON m.instance_id = v.instance_id
            ORDER BY a.relative_path COLLATE NOCASE
            """
        ).fetchall()
        fields = rows[0].keys() if rows else [
            "instance_id",
            "content_id",
            "original_path",
            "relative_path",
            "families",
            "review_status",
            "note",
            "model_families",
            "probabilities_json",
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))
        return path


class FamilyCheckPanel(QWidget):
    def __init__(self, family_options: list[str] | None = None):
        super().__init__()
        layout = QGridLayout(self)
        self.family_options = family_options or FAMILY_OPTIONS
        self.checkboxes: dict[str, QCheckBox] = {}
        self.mode = "multi"
        self._updating = False
        for index, family in enumerate(self.family_options):
            checkbox = QCheckBox(FAMILY_DISPLAY.get(family, family))
            checkbox.setToolTip(family)
            checkbox.setMinimumHeight(44)
            checkbox.stateChanged.connect(lambda _state, value=family: self.on_checkbox_changed(value))
            self.checkboxes[family] = checkbox
            layout.addWidget(checkbox, index // 2, index % 2)

    def set_mode(self, mode: str) -> None:
        self.mode = "single" if mode == "single" else "multi"
        if self.mode == "single":
            values = self.values()
            if len(values) > 1:
                self.set_values([values[0]])

    def on_checkbox_changed(self, family: str) -> None:
        if self._updating or self.mode != "single":
            return
        checkbox = self.checkboxes[family]
        if not checkbox.isChecked():
            return
        self._updating = True
        try:
            for other_family, other_checkbox in self.checkboxes.items():
                if other_family != family:
                    other_checkbox.setChecked(False)
        finally:
            self._updating = False

    def values(self) -> list[str]:
        return [family for family, checkbox in self.checkboxes.items() if checkbox.isChecked()]

    def set_values(self, families: list[str]) -> None:
        selected_values = [family for family in families if family in self.family_options]
        if self.mode == "single" and len(selected_values) > 1:
            selected_values = selected_values[:1]
        selected = set(selected_values)
        self._updating = True
        try:
            for family, checkbox in self.checkboxes.items():
                checkbox.setChecked(family in selected)
        finally:
            self._updating = False

    def on_changed(self, callback) -> None:
        for checkbox in self.checkboxes.values():
            checkbox.stateChanged.connect(callback)


class SegmentedButtonPanel(QWidget):
    def __init__(self, options: list[tuple[str, str]]):
        super().__init__()
        self.buttons: dict[str, QPushButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for label, value in options:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(30)
            self.buttons[value] = button
            self.group.addButton(button)
            layout.addWidget(button, 1)
        if options:
            self.buttons[options[0][1]].setChecked(True)
        self.group.buttonToggled.connect(lambda _button, checked: checked and self.apply_style())
        self.apply_style()

    def value(self) -> str:
        for value, button in self.buttons.items():
            if button.isChecked():
                return value
        return next(iter(self.buttons), "")

    def set_value(self, value: str) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)
        self.apply_style()

    def on_changed(self, callback) -> None:
        self.group.buttonToggled.connect(lambda _button, checked: checked and callback())

    def apply_style(self) -> None:
        for button in self.buttons.values():
            if button.isChecked():
                button.setStyleSheet("QPushButton { background: #1f6feb; color: white; font-weight: bold; }")
            else:
                button.setStyleSheet("")


class MainWindow(QMainWindow):
    def __init__(self, store: ReviewStore, config: dict[str, Any]):
        super().__init__()
        self.store = store
        self.config = config
        self.assets: list[FamilyAsset] = []
        self.current_index = -1
        self.current_asset: FamilyAsset | None = None
        self.loading = False
        self.instance_filter_ids = self.load_instance_filter_ids()
        self.family_options = self.config.get("family_options") or FAMILY_OPTIONS
        self.thumbnail_queue: list[int] = []
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setInterval(15)
        self.thumbnail_timer.timeout.connect(self.load_thumbnail_batch)
        self.previous_families: list[str] = []
        self.setWindowTitle("Ads Classifier Review - Visual Family Crops")
        self.resize(1350, 820)
        self.build_ui()
        self.load_filter_defaults()
        self.apply_filters()

    def load_instance_filter_ids(self) -> list[str]:
        path_text = self.config.get("instance_list_csv") or self.config.get("review_list_csv") or ""
        if not path_text:
            return []
        path = Path(path_text)
        if not path.is_absolute():
            path = project_root_from_file() / path
        if not path.exists():
            raise SystemExit(f"instance list CSV not found: {path}")
        column = str(self.config.get("instance_list_column", "instance_id"))
        ids: list[str] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                value = (row.get(column) or "").strip()
                if value and value not in ids:
                    ids.append(value)
        return ids

    def build_ui(self) -> None:
        splitter = QSplitter()
        splitter.addWidget(self.build_left_panel())
        splitter.addWidget(self.build_image_panel())
        splitter.addWidget(self.build_right_panel())
        splitter.setSizes([360, 650, 340])
        self.setCentralWidget(splitter)

        for shortcut, handler in [
            ("A", self.prev_image),
            ("D", self.next_image),
            ("Ctrl+Return", self.save_and_next),
            ("Ctrl+Enter", self.save_and_next),
            ("Ctrl+P", self.postpone),
            ("Ctrl+Left", self.prev_image),
            ("Ctrl+Right", self.next_image),
        ]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ApplicationShortcut)
            action.triggered.connect(handler)
            self.addAction(action)

    def build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(["unreviewed", "reviewed", "changed", "postponed", "all"])
        self.family_filter = QComboBox()
        self.family_filter.addItems(["all"] + self.family_options)
        self.source_filter = QComboBox()
        self.source_filter.addItems(["all"] + self.store.source_roots())
        self.sort_filter = QComboBox()
        self.sort_filter.addItems(["family", "confidence_low", "image", "path", "review_list"])
        self.path_contains_edit = QLineEdit()
        self.path_contains_edit.setPlaceholderText("path contains")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("search filename/path")
        form.addRow("Status", self.status_filter)
        form.addRow("Family", self.family_filter)
        form.addRow("Source", self.source_filter)
        form.addRow("Sort", self.sort_filter)
        form.addRow("Path", self.path_contains_edit)
        form.addRow("Search", self.search_edit)
        layout.addLayout(form)

        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)

        self.approve_btn = QPushButton("Approve Filtered")
        self.approve_btn.setToolTip("Mark all visible unreviewed items with a family suggestion as reviewed.")
        layout.addWidget(self.approve_btn)

        self.asset_list = QListWidget()
        self.asset_list.setIconSize(QSize(112, 72))
        self.asset_list.currentRowChanged.connect(self.load_asset)
        layout.addWidget(self.asset_list, 1)

        for widget in [self.status_filter, self.family_filter, self.source_filter, self.sort_filter]:
            widget.currentTextChanged.connect(self.apply_filters)
        self.search_edit.textChanged.connect(self.apply_filters)
        self.path_contains_edit.textChanged.connect(self.apply_filters)
        self.approve_btn.clicked.connect(self.approve_filtered)
        return panel

    def build_image_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setStyleSheet("QLabel { background: #202124; color: #ddd; }")
        layout.addWidget(self.image_label, 1)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        return panel

    def build_right_panel(self) -> QWidget:
        panel = QWidget()
        outer = QVBoxLayout(panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.hint_label = QLabel("Classifier crop review: choose the visual family for this crop. Model suggestion is not human truth.")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("QLabel { font-weight: bold; padding: 6px; background: #eef5ff; }")
        layout.addWidget(self.hint_label)

        self.suggestion_label = QLabel("")
        self.suggestion_label.setWordWrap(True)
        layout.addWidget(self.suggestion_label)

        controls = QFormLayout()
        self.default_pick_panel = SegmentedButtonPanel(
            [("Model", "model suggestion"), ("Previous", "previous saved")]
        )
        self.selection_mode_panel = SegmentedButtonPanel(
            [("Single", "single"), ("Multi", "multi")]
        )
        controls.addRow("Default pick", self.default_pick_panel)
        controls.addRow("Selection", self.selection_mode_panel)
        layout.addLayout(controls)

        layout.addWidget(QLabel("Human family"))
        self.family_panel = FamilyCheckPanel(self.family_options)
        self.family_panel.set_mode(self.selection_mode_panel.value())
        layout.addWidget(self.family_panel)

        quick_row = QHBoxLayout()
        self.use_suggestion_btn = QPushButton("Use Suggestion")
        self.use_previous_btn = QPushButton("Use Previous")
        quick_row.addWidget(self.use_suggestion_btn, 1)
        quick_row.addWidget(self.use_previous_btn, 1)
        layout.addLayout(quick_row)

        layout.addWidget(QLabel("Note"))
        self.note_edit = QTextEdit()
        self.note_edit.setMaximumHeight(110)
        layout.addWidget(self.note_edit)

        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)
        layout.addStretch(1)

        action_row = QHBoxLayout()
        self.save_btn = QPushButton("Save && Next")
        self.postpone_btn = QPushButton("Postpone")
        self.save_btn.setMinimumHeight(38)
        self.postpone_btn.setMinimumHeight(38)
        self.save_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        action_row.addWidget(self.save_btn, 1)
        action_row.addWidget(self.postpone_btn, 1)
        outer.addLayout(action_row)

        self.use_suggestion_btn.clicked.connect(self.use_suggestion)
        self.use_previous_btn.clicked.connect(self.use_previous)
        self.default_pick_panel.on_changed(self.apply_default_selection_to_current)
        self.selection_mode_panel.on_changed(self.on_selection_mode_changed)
        self.save_btn.clicked.connect(self.save_and_next)
        self.postpone_btn.clicked.connect(self.postpone)
        return panel

    def load_filter_defaults(self) -> None:
        defaults = self.config.get("default_filter", {})
        self.status_filter.setCurrentText(defaults.get("status", "unreviewed"))
        self.family_filter.setCurrentText(defaults.get("family", "all"))
        source = defaults.get("source", "all")
        if self.source_filter.findText(source) >= 0:
            self.source_filter.setCurrentText(source)
        self.sort_filter.setCurrentText(defaults.get("sort", "family"))
        self.default_pick_panel.set_value(defaults.get("default_pick", "model suggestion"))
        self.selection_mode_panel.set_value(defaults.get("selection_mode", "single"))
        self.family_panel.set_mode(self.selection_mode_panel.value())
        self.path_contains_edit.setText(defaults.get("path_contains", ""))
        self.search_edit.setText(defaults.get("search", ""))

    def apply_filters(self) -> None:
        if self.loading:
            return
        exclude = self.config.get("exclude_path_contains", [])
        self.assets = self.store.query_assets(
            status=self.status_filter.currentText(),
            family=self.family_filter.currentText(),
            search=self.search_edit.text().strip(),
            path_contains=self.path_contains_edit.text().strip(),
            exclude_path_contains=[str(item) for item in exclude],
            source_root=self.source_filter.currentText(),
            sort_mode=self.sort_filter.currentText(),
            instance_ids=self.instance_filter_ids,
        )
        self.asset_list.blockSignals(True)
        self.asset_list.clear()
        for asset in self.assets[:1200]:
            self.asset_list.addItem(self.list_item(asset))
        self.thumbnail_queue = list(range(min(len(self.assets), 1200)))
        self.asset_list.blockSignals(False)
        self.thumbnail_timer.start()
        self.update_progress()
        if self.assets:
            self.asset_list.setCurrentRow(0)
        else:
            self.current_asset = None
            self.current_index = -1
            self.image_label.setText("No images in current filter.")
            self.path_label.setText("")
            self.suggestion_label.setText("")
            self.meta_label.setText("")

    def list_item(self, asset: FamilyAsset) -> QListWidgetItem:
        fam = "|".join(asset.effective_families) or "-"
        suggestion = "|".join(asset.suggestion_families) or "-"
        text = f"{asset.filename}\n{asset.display_status} | {fam}\nmodel: {suggestion} {asset.top_probability:.2f}"
        item = QListWidgetItem(text)
        item.setToolTip(asset.relative_path)
        return item

    def set_item_thumbnail(self, item: QListWidgetItem, asset: FamilyAsset) -> None:
        pixmap = QPixmap(asset.original_path)
        if not pixmap.isNull():
            item.setIcon(QIcon(pixmap.scaled(112, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def load_thumbnail_batch(self) -> None:
        if not self.thumbnail_queue:
            self.thumbnail_timer.stop()
            return
        for _ in range(16):
            if not self.thumbnail_queue:
                self.thumbnail_timer.stop()
                return
            index = self.thumbnail_queue.pop(0)
            if index >= self.asset_list.count() or index >= len(self.assets):
                continue
            item = self.asset_list.item(index)
            if item is not None:
                self.set_item_thumbnail(item, self.assets[index])

    def load_asset(self, index: int) -> None:
        if index < 0 or index >= len(self.assets):
            return
        self.current_index = index
        self.current_asset = self.assets[index]
        asset = self.current_asset
        self.refresh_image_pixmap(asset)
        selected = self.default_families_for(asset)
        self.family_panel.set_values(selected)
        self.note_edit.setPlainText(asset.note if asset.display_status == "reviewed" else "")
        probs = ", ".join(f"{key}:{value:.2f}" for key, value in sorted(asset.probabilities.items(), key=lambda kv: kv[1], reverse=True))
        self.suggestion_label.setText(
            f"Suggestion: {'|'.join(asset.suggestion_families) or '-'}\n"
            f"Source: {asset.suggestion_source or '-'}\n"
            f"Probabilities: {probs or '-'}"
        )
        self.path_label.setText(f"{asset.relative_path}\n{asset.width}x{asset.height}")
        self.meta_label.setText(
            f"instance_id: {asset.instance_id}\n"
            f"content_id: {asset.content_id}\n"
            f"source_root: {asset.source_root}\n"
            f"asset_role: {asset.asset_role} | image_scope: {asset.image_scope}"
        )
        self.update_previous_button()
        self.update_progress()

    def refresh_image_pixmap(self, asset: FamilyAsset) -> None:
        pixmap = QPixmap(asset.original_path)
        if pixmap.isNull():
            self.image_label.setText(f"Image load failed:\n{asset.original_path}")
        else:
            target = self.image_label.size()
            if target.width() < 50 or target.height() < 50:
                target = QSize(650, 650)
            self.image_label.setPixmap(pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.current_asset is not None:
            self.refresh_image_pixmap(self.current_asset)

    def use_suggestion(self) -> None:
        if self.current_asset is None:
            return
        self.family_panel.set_values(self.current_asset.suggestion_families)

    def use_previous(self) -> None:
        if not self.previous_families:
            return
        self.family_panel.set_values(self.previous_families)

    def default_families_for(self, asset: FamilyAsset) -> list[str]:
        valid_human_families = [family for family in asset.human_families if family in self.family_options]
        if asset.display_status == "reviewed" and valid_human_families:
            return valid_human_families
        if self.default_pick_panel.value() == "previous saved" and self.previous_families:
            return self.previous_families
        return [family for family in asset.suggestion_families if family in self.family_options]

    def apply_default_selection_to_current(self) -> None:
        if self.loading or self.current_asset is None:
            return
        self.family_panel.set_values(self.default_families_for(self.current_asset))
        self.update_previous_button()

    def on_selection_mode_changed(self) -> None:
        self.family_panel.set_mode(self.selection_mode_panel.value())
        self.update_previous_button()

    def update_previous_button(self) -> None:
        text = "|".join(self.previous_families) if self.previous_families else "-"
        self.use_previous_btn.setText(f"Use Previous ({text})")
        self.use_previous_btn.setEnabled(bool(self.previous_families))

    def save_and_next(self) -> None:
        if self.current_asset is None:
            return
        families = self.family_panel.values()
        if not families:
            QMessageBox.warning(self, "Missing family", "Choose at least one family, or use uncertain/postpone.")
            return
        self.store.save_review(self.current_asset, families, "reviewed", self.note_edit.toPlainText())
        self.previous_families = families
        self.update_previous_button()
        self.remove_current_or_next()

    def postpone(self) -> None:
        if self.current_asset is None:
            return
        families = self.family_panel.values() or self.current_asset.suggestion_families
        self.store.save_review(self.current_asset, families, "postponed", self.note_edit.toPlainText())
        self.remove_current_or_next()

    def remove_current_or_next(self) -> None:
        idx = self.current_index
        if self.status_filter.currentText() == "changed":
            self.remove_current_from_visible_list(idx)
            return
        if self.status_filter.currentText() in {"unreviewed", "postponed", "reviewed"}:
            self.apply_filters()
            return
        if idx + 1 < len(self.assets):
            self.asset_list.setCurrentRow(idx + 1)

    def remove_current_from_visible_list(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.assets):
            return
        self.asset_list.blockSignals(True)
        self.asset_list.takeItem(idx)
        self.assets.pop(idx)
        self.asset_list.blockSignals(False)
        self.update_progress()
        if not self.assets:
            self.current_asset = None
            self.current_index = -1
            self.image_label.setText("No images in current filter.")
            self.path_label.setText("")
            self.suggestion_label.setText("")
            self.meta_label.setText("")
            return
        next_idx = min(idx, len(self.assets) - 1)
        self.asset_list.setCurrentRow(next_idx)

    def approve_filtered(self) -> None:
        candidates = [
            asset
            for asset in self.assets
            if asset.display_status == "unreviewed" and asset.effective_families
        ]
        if not candidates:
            QMessageBox.information(self, "Nothing to approve", "No visible unreviewed items with a suggestion.")
            return
        counts = Counter("|".join(asset.effective_families) for asset in candidates)
        summary = "\n".join(f"{family or '-'}: {count}" for family, count in counts.most_common(12))
        reply = QMessageBox.question(
            self,
            "Approve filtered",
            f"Mark {len(candidates)} visible suggestion(s) as reviewed?\n\n{summary}\n\nOnly do this after checking the thumbnails.",
        )
        if reply != QMessageBox.Yes:
            return
        for asset in candidates:
            self.store.save_review(asset, asset.effective_families, "reviewed", asset.note)
        self.apply_filters()

    def update_progress(self) -> None:
        counts = self.store.counts()
        shown = min(len(self.assets), 1200)
        self.progress_label.setText(
            f"Filtered {len(self.assets)} (shown {shown}) | reviewed {counts['reviewed']} | "
            f"postponed {counts['postponed']} | model suggestions {counts['suggestions']}"
        )

    def prev_image(self) -> None:
        if self.current_index > 0:
            self.asset_list.setCurrentRow(self.current_index - 1)

    def next_image(self) -> None:
        if self.current_index + 1 < min(len(self.assets), self.asset_list.count()):
            self.asset_list.setCurrentRow(self.current_index + 1)


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise SystemExit(f"config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Focused Ads visual-family crop review GUI.")
    parser.add_argument("--project-root", type=Path, default=project_root_from_file())
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()

    db_path = args.db if args.db.is_absolute() else args.project_root / args.db
    config = load_config(args.config)
    app = QApplication(sys.argv)
    store = ReviewStore(db_path)
    window = MainWindow(store, config)
    window.show()
    try:
        return app.exec()
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
