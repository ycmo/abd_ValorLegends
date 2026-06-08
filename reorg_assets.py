import os
import shutil
from pathlib import Path

base_dir = Path(r"E:\antigravity\adb_vl")
ads_dir = base_dir / "ads"
ads2_dir = base_dir / "ads2"

# 定義新的資產分類架構
assets_dir = ads2_dir / "assets"
cat1_dir = assets_dir / "1_templates"
cat2_dir = assets_dir / "2_communication"
cat3_dir = assets_dir / "3_reference_screens"
debug_dir = ads2_dir / "debug"

# 建立新目錄
for d in [cat1_dir, cat2_dir, cat3_dir, debug_dir]:
    d.mkdir(parents=True, exist_ok=True)

# 1. 移動現有的 templates 到 1_templates 中
for sub in ["nav_icons", "close_icons", "scene_anchors"]:
    src_sub = assets_dir / sub
    if src_sub.exists():
        dst_sub = cat1_dir / sub
        # 如果 dst_sub 已經存在，我們還是把裡面的檔案搬過去
        dst_sub.mkdir(exist_ok=True)
        for f in src_sub.glob("*"):
            if f.is_file():
                shutil.move(str(f), str(dst_sub / f.name))
        # 搬完後刪除舊目錄
        src_sub.rmdir()

# 2. 處理從 ads 來的剩餘截圖，將它們歸類到 3_reference_screens
# 包含 ads/assets/ 和 ads/captures/ 下的各種 PNG 檔
def copy_pngs_to_ref(src_dir):
    if src_dir.exists():
        for f in src_dir.glob("*.png"):
            if f.is_file() and not (cat3_dir / f.name).exists():
                shutil.copy2(f, cat3_dir / f.name)
        for f in src_dir.glob("*.PNG"):
            if f.is_file() and not (cat3_dir / f.name).exists():
                shutil.copy2(f, cat3_dir / f.name)

copy_pngs_to_ref(ads_dir / "assets")
copy_pngs_to_ref(ads_dir / "captures")
copy_pngs_to_ref(ads_dir)

print("目錄架構重組完成！")
