from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads2.tools.scan_x_geometry_candidates import make_sheet


def parse_roi_top_ratio(lines):
    for line in lines:
        line = line.strip()
        if not line.startswith("ROI: top "):
            continue
        value = line.removeprefix("ROI: top ").removesuffix("%")
        try:
            return float(value) / 100.0
        except ValueError:
            return 0.40
    return 0.40


def clean_code(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def parse_rows(report_path: Path):
    lines = report_path.read_text(encoding="utf-8").splitlines()
    rows = []
    for line in lines:
        if not line.startswith("| "):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) < 12 or parts[0] == "score" or parts[0].startswith("---"):
            continue
        try:
            if len(parts) >= 14:
                continuity = float(parts[11])
                max_gap_ratio = float(parts[12])
                path_part = parts[-1]
            else:
                continuity = 0.0
                max_gap_ratio = 0.0
                path_part = parts[11]
            path = Path(clean_code(path_part))
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            row = {
                "score": float(parts[0]),
                "method": parts[1],
                "gate": parts[2],
                "box": tuple(ast.literal_eval(clean_code(parts[3]))),
                "angle_down": float(parts[4]),
                "angle_up": float(parts[5]),
                "length_ratio": float(parts[6]),
                "center_offset": float(parts[7]),
                "axis_union": float(parts[8]),
                "axis_balance": float(parts[9]),
                "fill": float(parts[10]),
                "continuity": continuity,
                "max_gap_ratio": max_gap_ratio,
                "path": path,
            }
            if len(parts) >= 21:
                row.update(
                    {
                        "axis_span_down_px": float(parts[13]),
                        "axis_span_up_px": float(parts[14]),
                        "min_arm_pixels": int(parts[15]),
                        "min_arm_extent_px": float(parts[16]),
                        "min_arm_coverage": float(parts[17]),
                        "center_pixels": int(parts[18]),
                        "center_thickness_ratio": float(parts[19]),
                    }
                )
            if len(parts) >= 28:
                row.update(
                    {
                        "axis_core_union": float(parts[20]),
                        "axis_core_balance": float(parts[21]),
                        "fit_error": float(parts[22]),
                        "extra_error": float(parts[23]),
                        "missing_error": float(parts[24]),
                        "center_extra_error": float(parts[25]),
                        "stroke_width": float(parts[26]),
                    }
                )
            rows.append(row)
        except (SyntaxError, ValueError):
            continue
    return rows, parse_roi_top_ratio(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a debug overlay sheet from an X geometry scan_report.md.")
    parser.add_argument("scan_dir", type=Path)
    parser.add_argument("--items", type=int, default=100)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report_path = args.scan_dir / "scan_report.md"
    if not report_path.exists():
        raise SystemExit(f"Missing report: {report_path}")

    rows, roi_top_ratio = parse_rows(report_path)
    if not rows:
        raise SystemExit(f"No rows found in report: {report_path}")

    output = args.output or (args.scan_dir / "hits_debug_top100.png")
    make_sheet(rows, output, max_items=args.items, roi_top_ratio=roi_top_ratio, debug_overlay=True)
    print("debug sheet:", output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
