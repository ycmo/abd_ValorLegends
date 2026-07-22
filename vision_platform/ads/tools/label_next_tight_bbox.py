from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


DEFAULT_MANIFEST = Path(
    "vision_platform/ads/pilot/visual_family_smoke_20260719/"
    "development_retrain_single_family/training_pool/manifest.csv"
)
DEFAULT_OUTPUT = Path(
    "vision_platform/ads/pilot/visual_family_smoke_20260719/"
    "next_tight_bbox/next_tight_bbox.csv"
)


@dataclass
class NextSample:
    instance_id: str
    content_id: str
    image_path: Path
    variant: str = "unknown"
    note: str = ""
    bbox: tuple[int, int, int, int] | None = None


def read_next_samples(manifest: Path) -> list[NextSample]:
    samples: list[NextSample] = []
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            families = (row.get("families") or "").split("|")
            if "next" not in families:
                continue
            image_path = Path(row["image_path"])
            samples.append(
                NextSample(
                    instance_id=row.get("instance_id", ""),
                    content_id=row.get("content_id", ""),
                    image_path=image_path,
                )
            )
    return samples


def load_existing(path: Path, samples: list[NextSample]) -> None:
    if not path.exists():
        return
    by_instance = {sample.instance_id: sample for sample in samples}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sample = by_instance.get(row.get("instance_id", ""))
            if sample is None:
                continue
            try:
                x = int(float(row.get("x", "")))
                y = int(float(row.get("y", "")))
                w = int(float(row.get("w", "")))
                h = int(float(row.get("h", "")))
            except ValueError:
                continue
            if w > 0 and h > 0:
                sample.bbox = (x, y, w, h)
            sample.variant = row.get("variant") or sample.variant
            sample.note = row.get("note") or sample.note


def write_samples(path: Path, samples: list[NextSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["instance_id", "content_id", "image_path", "x", "y", "w", "h", "variant", "note"]
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in samples:
            x = y = w = h = ""
            if sample.bbox is not None:
                x, y, w, h = sample.bbox
            writer.writerow(
                {
                    "instance_id": sample.instance_id,
                    "content_id": sample.content_id,
                    "image_path": str(sample.image_path),
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "variant": sample.variant,
                    "note": sample.note,
                }
            )
    tmp_path.replace(path)


class BBoxCanvas(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(QSize(520, 520))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #202124; color: #ddd;")
        self.pixmap_original: QPixmap | None = None
        self.image_size = QSize(0, 0)
        self.draw_rect: QRect | None = None
        self.drag_start: QPoint | None = None
        self.display_rect = QRect()
        self.on_bbox_changed = None

    def set_image(self, path: Path, bbox: tuple[int, int, int, int] | None) -> None:
        image = QImage(str(path))
        if image.isNull():
            self.pixmap_original = None
            self.image_size = QSize(0, 0)
            self.draw_rect = None
            self.setText(f"Cannot load image:\n{path}")
            return
        self.pixmap_original = QPixmap.fromImage(image)
        self.image_size = image.size()
        self.draw_rect = QRect(*bbox) if bbox is not None else None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        if self.pixmap_original is None or self.pixmap_original.isNull():
            return
        scaled = self.pixmap_original.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self.display_rect = QRect(x, y, scaled.width(), scaled.height())
        painter.drawPixmap(x, y, scaled)
        if self.draw_rect is not None:
            rect = self.image_to_widget_rect(self.draw_rect)
            painter.setPen(QPen(QColor(255, 80, 30), 2))
            painter.setBrush(QBrush(QColor(255, 80, 30, 45)))
            painter.drawRect(rect)

    def widget_to_image_point(self, point: QPoint) -> QPoint:
        if self.image_size.width() <= 0 or self.display_rect.width() <= 0:
            return QPoint(0, 0)
        x = (point.x() - self.display_rect.x()) * self.image_size.width() / self.display_rect.width()
        y = (point.y() - self.display_rect.y()) * self.image_size.height() / self.display_rect.height()
        x = max(0, min(self.image_size.width() - 1, round(x)))
        y = max(0, min(self.image_size.height() - 1, round(y)))
        return QPoint(x, y)

    def image_to_widget_rect(self, rect: QRect) -> QRect:
        if self.image_size.width() <= 0 or self.image_size.height() <= 0:
            return QRect()
        x = self.display_rect.x() + round(rect.x() * self.display_rect.width() / self.image_size.width())
        y = self.display_rect.y() + round(rect.y() * self.display_rect.height() / self.image_size.height())
        w = round(rect.width() * self.display_rect.width() / self.image_size.width())
        h = round(rect.height() * self.display_rect.height() / self.image_size.height())
        return QRect(x, y, w, h)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self.pixmap_original is None:
            return
        self.drag_start = self.widget_to_image_point(event.position().toPoint())
        self.draw_rect = QRect(self.drag_start, self.drag_start)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.drag_start is None:
            return
        current = self.widget_to_image_point(event.position().toPoint())
        self.draw_rect = QRect(self.drag_start, current).normalized()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self.drag_start is None:
            return
        current = self.widget_to_image_point(event.position().toPoint())
        self.draw_rect = QRect(self.drag_start, current).normalized()
        self.drag_start = None
        if self.draw_rect.width() < 2 or self.draw_rect.height() < 2:
            self.draw_rect = None
        if self.on_bbox_changed:
            bbox = None
            if self.draw_rect is not None:
                bbox = (
                    self.draw_rect.x(),
                    self.draw_rect.y(),
                    self.draw_rect.width(),
                    self.draw_rect.height(),
                )
            self.on_bbox_changed(bbox)
        self.update()


class NextBBoxWindow(QMainWindow):
    def __init__(self, samples: list[NextSample], output: Path) -> None:
        super().__init__()
        self.samples = samples
        self.output = output
        self.index = 0
        self.setWindowTitle("Next Tight BBox Labeler")
        self.resize(900, 700)

        self.canvas = BBoxCanvas()
        self.canvas.on_bbox_changed = self.set_current_bbox
        self.status = QLabel()
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.variant = QComboBox()
        self.variant.addItems(["unknown", "large_pill", "tiny_pill", "play_text", "text_only"])
        self.variant.currentTextChanged.connect(self.set_current_variant)
        self.note = QLineEdit()
        self.note.textEdited.connect(self.set_current_note)

        prev_button = QPushButton("Previous")
        next_button = QPushButton("Save and Next")
        clear_button = QPushButton("Clear BBox")
        save_button = QPushButton("Save CSV")
        open_button = QPushButton("Open Output Folder")
        prev_button.clicked.connect(self.previous_sample)
        next_button.clicked.connect(self.next_sample)
        clear_button.clicked.connect(self.clear_bbox)
        save_button.clicked.connect(self.save)
        open_button.clicked.connect(self.open_output_folder)

        controls = QHBoxLayout()
        controls.addWidget(prev_button)
        controls.addWidget(next_button)
        controls.addWidget(clear_button)
        controls.addWidget(save_button)
        controls.addWidget(open_button)

        meta = QHBoxLayout()
        meta.addWidget(QLabel("Variant"))
        meta.addWidget(self.variant)
        meta.addWidget(QLabel("Note"))
        meta.addWidget(self.note, 1)

        layout = QVBoxLayout()
        layout.addWidget(self.status)
        layout.addWidget(self.path_label)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(meta)
        layout.addLayout(controls)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)
        self.load_current()

    def set_current_bbox(self, bbox: tuple[int, int, int, int] | None) -> None:
        self.samples[self.index].bbox = bbox
        self.save()
        self.update_status()

    def set_current_variant(self, value: str) -> None:
        self.samples[self.index].variant = value
        self.save()

    def set_current_note(self, value: str) -> None:
        self.samples[self.index].note = value
        self.save()

    def update_status(self) -> None:
        done = sum(1 for sample in self.samples if sample.bbox is not None)
        sample = self.samples[self.index]
        bbox_text = sample.bbox if sample.bbox is not None else "not set"
        self.status.setText(f"{self.index + 1}/{len(self.samples)}  done={done}  bbox={bbox_text}")

    def load_current(self) -> None:
        if not self.samples:
            self.status.setText("No next samples found.")
            return
        sample = self.samples[self.index]
        self.path_label.setText(f"{sample.instance_id}  {sample.image_path}")
        self.variant.blockSignals(True)
        self.variant.setCurrentText(sample.variant)
        self.variant.blockSignals(False)
        self.note.blockSignals(True)
        self.note.setText(sample.note)
        self.note.blockSignals(False)
        self.canvas.set_image(sample.image_path, sample.bbox)
        self.update_status()

    def save(self) -> None:
        write_samples(self.output, self.samples)

    def next_sample(self) -> None:
        self.save()
        if self.index < len(self.samples) - 1:
            self.index += 1
        self.load_current()

    def previous_sample(self) -> None:
        self.save()
        if self.index > 0:
            self.index -= 1
        self.load_current()

    def clear_bbox(self) -> None:
        self.samples[self.index].bbox = None
        self.save()
        self.load_current()

    def open_output_folder(self) -> None:
        folder = self.output.parent
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # type: ignore[attr-defined]

    def closeEvent(self, event) -> None:  # noqa: N802
        self.save()
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Small UI for labeling tight Next bboxes.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    samples = read_next_samples(args.manifest)
    load_existing(args.output, samples)
    app = QApplication(sys.argv)
    window = NextBBoxWindow(samples, args.output)
    window.show()
    if not samples:
        QMessageBox.warning(window, "No samples", f"No next samples found in {args.manifest}")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
