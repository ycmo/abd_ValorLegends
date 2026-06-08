import os
import shutil
from pathlib import Path

base_dir = Path(r"E:\antigravity\adb_vl")
ads_dir = base_dir / "ads"
ads2_dir = base_dir / "ads2"

# Create ads2 structure
dirs_to_create = [
    ads2_dir,
    ads2_dir / "assets",
    ads2_dir / "assets" / "nav_icons",
    ads2_dir / "assets" / "close_icons",
    ads2_dir / "assets" / "scene_anchors",
    ads2_dir / "src",
    ads2_dir / "src" / "states"
]

for d in dirs_to_create:
    d.mkdir(parents=True, exist_ok=True)

# Copy and reorganize assets
src_entry = ads_dir / "assets" / "entry"
if src_entry.exists():
    for f in src_entry.glob("*"):
        if f.is_file():
            shutil.copy2(f, ads2_dir / "assets" / "nav_icons" / f.name)

src_close = ads_dir / "assets" / "ad_close"
if src_close.exists():
    for f in src_close.glob("*"):
        if f.is_file():
            shutil.copy2(f, ads2_dir / "assets" / "close_icons" / f.name)

src_anchors = ads_dir / "assets" / "anchors"
if src_anchors.exists():
    for f in src_anchors.glob("*"):
        if f.is_file():
            shutil.copy2(f, ads2_dir / "assets" / "scene_anchors" / f.name)

print("ads2 structure created and assets copied.")
