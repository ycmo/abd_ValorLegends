import os
from dataclasses import dataclass
from pathlib import Path

_THIS_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
_ADS2_DIR = _THIS_DIR.parent

@dataclass
class AdConfig:
    serial: str = "emulator-5554"
    initial_wait_seconds: float = 30.0
    timeout_seconds: float = 120.0
    interval: float = 1.0
    threshold: float = 0.82
    anchor_threshold: float = 0.80
    debug: bool = False
    max_tap_attempts: int = 5

    # 目錄與路徑配置
    assets_dir: Path = _ADS2_DIR / "assets"
    cat1_dir: Path = assets_dir / "1_templates"
    cat2_dir: Path = assets_dir / "2_communication"
    cat3_dir: Path = assets_dir / "3_reference_screens"
    
    nav_icons_dir: Path = cat1_dir / "nav_icons"
    close_icons_dir: Path = cat1_dir / "close_icons"
    scene_anchors_dir: Path = cat1_dir / "scene_anchors"
    
    debug_dir: Path = _ADS2_DIR / "debug"
    captures_dir: Path = _ADS2_DIR / "captures"
