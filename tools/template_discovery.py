"""
template_discovery.py
---------------------
Template Discovery CLI 工具。

用途：開發階段把 debug screenshot 轉換成 validated template 的完整流程工具。

核心流程：
  debug screenshot (FAILED)
    → discover-template    → pending_analysis record
    → ai-analyze           → ai_analysis_result + candidates
    → add-candidate        → candidate_templates record
    → crop-candidate       → 裁切 PNG 到 template_candidates/
    → validate-template    → validation_result (OpenCV)
    → promote-template     → 複製到 experiments/ad_closer/assets/ad_close/

與主線的關係：
  ❌ 不被 src/main.py import
  ❌ 不被 run_ad_closer.py import
  ❌ 不被任何 bot runtime 呼叫
  ✅ 只讀 debug screenshot，輸出 validated template

執行方式（從專案根目錄）：
  python tools/template_discovery.py <subcommand> [options]
  python tools/template_discovery.py --help
"""

import argparse
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ── 路徑設定 ─────────────────────────────────────────────────────
_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.dirname(_THIS_DIR)
_DATA_DIR  = os.path.join(_ROOT, "data", "template_discovery")
_CROPS_DIR = os.path.join(_ROOT, "template_candidates")

# JSONL 檔案路徑
_PENDING_FILE    = os.path.join(_DATA_DIR, "pending_analysis.jsonl")
_AI_RESULTS_FILE = os.path.join(_DATA_DIR, "ai_analysis_results.jsonl")
_CANDIDATES_FILE = os.path.join(_DATA_DIR, "candidate_templates.jsonl")
_VALIDATIONS_FILE= os.path.join(_DATA_DIR, "validation_results.jsonl")
_LIBRARY_FILE    = os.path.join(_DATA_DIR, "template_library.jsonl")

SEP = "─" * 62


# ══════════════════════════════════════════════════════════════════
# 資料層：JSONL 工具函式
# ══════════════════════════════════════════════════════════════════

def _ensure_dirs() -> None:
    """確保所有資料目錄存在，並建立空的 JSONL 檔案。"""
    os.makedirs(_DATA_DIR,  exist_ok=True)
    os.makedirs(_CROPS_DIR, exist_ok=True)
    for p in [_PENDING_FILE, _AI_RESULTS_FILE, _CANDIDATES_FILE,
              _VALIDATIONS_FILE, _LIBRARY_FILE]:
        if not os.path.exists(p):
            Path(p).touch()


def _make_id(prefix: str) -> str:
    ts   = time.strftime("%Y%m%d_%H%M%S")
    rand = random.randint(100, 999)
    return f"{prefix}_{ts}_{rand}"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _append(filepath: str, record: dict) -> None:
    """將一筆 record 附加到 JSONL 檔案末尾。"""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_all(filepath: str) -> list[dict]:
    """載入 JSONL 中的所有 record。"""
    records = []
    if not os.path.exists(filepath):
        return records
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _find_by_id(filepath: str, record_id: str) -> Optional[dict]:
    """從 JSONL 中找到 id == record_id 的第一筆。"""
    for r in _load_all(filepath):
        if r.get("id") == record_id:
            return r
    return None


def _update_record(filepath: str, record_id: str, updates: dict) -> bool:
    """
    重寫 JSONL，將 id == record_id 的 record 更新為 updates 的 merge 結果。
    回傳 True 表示找到並更新成功。
    """
    records = _load_all(filepath)
    found = False
    for r in records:
        if r.get("id") == record_id:
            r.update(updates)
            found = True
    if found:
        with open(filepath, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return found


# ══════════════════════════════════════════════════════════════════
# 子指令實作
# ══════════════════════════════════════════════════════════════════

# ── discover-template ──────────────────────────────────────────────

def cmd_discover_template(args: argparse.Namespace) -> None:
    """
    把 debug screenshot 登記為 pending_analysis record。
    不做任何 AI 分析或 OpenCV，只建立資料記錄。
    """
    _ensure_dirs()

    screenshot = os.path.abspath(args.screenshot)
    if not os.path.exists(screenshot):
        print(f"❌ 截圖不存在: {screenshot!r}")
        sys.exit(1)

    record_id = _make_id("pa")
    record = {
        "id":             record_id,
        "created_at":     _now_iso(),
        "screenshot_path": screenshot,
        "screen_type":    args.screen_type,
        "target_hint":    args.target,
        "source_module":  args.source_module,
        "trigger_reason": args.reason,
        "best_conf_seen": args.best_conf,
        "status":         "pending",
        "notes":          args.notes,
    }
    _append(_PENDING_FILE, record)

    print(SEP)
    print(f"[discover-template] 建立 pending_analysis record")
    print(f"  ID            : {record_id}")
    print(f"  Screenshot    : {screenshot}")
    print(f"  Screen type   : {args.screen_type}")
    print(f"  Target hint   : {args.target}")
    print(f"  Status        : pending")
    print(SEP)
    print(f"\n下一步（AI 分析）：")
    print(f"  python tools/template_discovery.py ai-analyze "
          f"--pending-id {record_id} --provider chatgpt")
    print(f"\n或手動建立候選（已知 bbox）：")
    print(f"  python tools/template_discovery.py add-candidate "
          f"--pending-id {record_id} --label close_button "
          f"--bbox 1496,20,1544,68 --source human")


# ── add-candidate ─────────────────────────────────────────────────

def cmd_add_candidate(args: argparse.Namespace) -> None:
    """
    手動新增一個候選 template（已知 bbox，不需 AI 分析）。
    """
    _ensure_dirs()

    # 解析 bbox
    try:
        parts = [int(x.strip()) for x in args.bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        x1, y1, x2, y2 = parts
    except ValueError:
        print("❌ bbox 格式錯誤，應為 x1,y1,x2,y2，例如：1496,20,1544,68")
        sys.exit(1)

    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2

    # 取得 screenshot 路徑（從 pending record 或直接指定）
    screenshot_path = ""
    if args.pending_id:
        pending = _find_by_id(_PENDING_FILE, args.pending_id)
        if pending is None:
            print(f"❌ 找不到 pending_analysis: {args.pending_id!r}")
            sys.exit(1)
        screenshot_path = pending["screenshot_path"]
    elif args.screenshot:
        screenshot_path = os.path.abspath(args.screenshot)
    else:
        print("❌ 請提供 --pending-id 或 --screenshot")
        sys.exit(1)

    record_id = _make_id("ct")
    record = {
        "id":               record_id,
        "created_at":       _now_iso(),
        "pending_id":       args.pending_id or "",
        "ai_result_id":     "",
        "label":            args.label,
        "target_label":     args.target_label or args.label.replace(" ", "_"),
        "source_screenshot": screenshot_path,
        "crop_path":        "",     # crop-candidate 後填入
        "bbox":             {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "center":           [cx, cy],
        "screen_type":      args.screen_type,
        "source":           args.source,    # human / ai / manual
        "status":           "candidate",
        "validation_id":    "",
        "promoted_to":      "",
        "notes":            args.notes,
    }
    _append(_CANDIDATES_FILE, record)

    print(SEP)
    print(f"[add-candidate] 建立 candidate record")
    print(f"  ID            : {record_id}")
    print(f"  Label         : {args.label}")
    print(f"  BBox          : [{x1}, {y1}, {x2}, {y2}]  center=({cx}, {cy})")
    print(f"  Source        : {args.source}")
    print(f"  Status        : candidate")
    print(SEP)
    print(f"\n下一步（裁切圖片）：")
    print(f"  python tools/template_discovery.py crop-candidate --id {record_id}")


# ── crop-candidate ────────────────────────────────────────────────

def cmd_crop_candidate(args: argparse.Namespace) -> None:
    """
    根據 candidate record 中的 bbox 裁切圖片，儲存到 template_candidates/。
    """
    _ensure_dirs()

    try:
        import cv2
        import numpy as np
    except ImportError:
        print("❌ 需要 opencv-python：pip install opencv-python")
        sys.exit(1)

    record = _find_by_id(_CANDIDATES_FILE, args.id)
    if record is None:
        print(f"❌ 找不到 candidate: {args.id!r}")
        sys.exit(1)

    screenshot = record["source_screenshot"]
    if not os.path.exists(screenshot):
        print(f"❌ 截圖不存在: {screenshot!r}")
        sys.exit(1)

    img = cv2.imread(screenshot)
    if img is None:
        print(f"❌ 無法讀取截圖: {screenshot!r}")
        sys.exit(1)

    bbox = record["bbox"]
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
    pad = args.padding

    # 加 padding（不超出圖片邊界）
    h, w = img.shape[:2]
    x1p = max(0, x1 - pad)
    y1p = max(0, y1 - pad)
    x2p = min(w, x2 + pad)
    y2p = min(h, y2 + pad)

    crop = img[y1p:y2p, x1p:x2p]
    if crop.size == 0:
        print(f"❌ 裁切結果為空，請確認 bbox 座標正確")
        sys.exit(1)

    # 儲存
    crop_filename = f"{args.id}.png"
    crop_path = os.path.join(_CROPS_DIR, crop_filename)
    cv2.imwrite(crop_path, crop)

    # 更新 candidate record
    _update_record(_CANDIDATES_FILE, args.id, {"crop_path": crop_path})

    ch, cw = crop.shape[:2]
    print(SEP)
    print(f"[crop-candidate] 裁切完成")
    print(f"  Candidate ID  : {args.id}")
    print(f"  BBox          : [{x1}, {y1}, {x2}, {y2}]  (padding={pad})")
    print(f"  Crop size     : {cw}x{ch}px")
    print(f"  Saved to      : {crop_path}")
    print(SEP)
    print(f"\n下一步（OpenCV 驗證）：")
    print(f"  python tools/template_discovery.py validate-template --id {args.id}")
    if args.preview:
        print(f"\n[crop-candidate] 開啟預覽...")
        try:
            import subprocess
            subprocess.Popen(["explorer", crop_path])
        except Exception:
            pass


# ── validate-template ─────────────────────────────────────────────

def cmd_validate_template(args: argparse.Namespace) -> None:
    """
    對候選 template 執行 OpenCV TM_CCOEFF_NORMED 驗證。
    使用 --live 時直接對模擬器截圖（需要 ADB 連線）。
    """
    _ensure_dirs()

    try:
        import cv2
        import numpy as np
    except ImportError:
        print("❌ 需要 opencv-python：pip install opencv-python")
        sys.exit(1)

    record = _find_by_id(_CANDIDATES_FILE, args.id)
    if record is None:
        print(f"❌ 找不到 candidate: {args.id!r}")
        sys.exit(1)

    crop_path = record.get("crop_path", "")
    if not crop_path or not os.path.exists(crop_path):
        print(f"❌ Crop 不存在: {crop_path!r}")
        print("   請先執行 crop-candidate")
        sys.exit(1)

    # 取得測試截圖
    if args.live:
        print("[validate] 對模擬器即時擷圖...")
        # 動態 import adb_controller 避免正式 bot 誤用
        sys.path.insert(0, os.path.join(_ROOT, "src"))
        try:
            from adb_controller import DeviceController, AdbControllerError
            ctrl = DeviceController(serial=args.serial)
            if not ctrl.connect():
                print(f"❌ 無法連線 ADB: {args.serial!r}")
                sys.exit(1)
            screen = ctrl.screenshot()
            import tempfile
            tmp_path = os.path.join(_DATA_DIR, f"validate_live_{int(time.time())}.png")
            cv2.imwrite(tmp_path, screen)
            test_screenshot = tmp_path
            print(f"[validate] 截圖已儲存到: {tmp_path}")
        except Exception as e:
            print(f"❌ 即時擷圖失敗: {e}")
            sys.exit(1)
    else:
        test_screenshot = os.path.abspath(args.screenshot) if args.screenshot else ""
        if not test_screenshot or not os.path.exists(test_screenshot):
            print(f"❌ 測試截圖不存在: {test_screenshot!r}")
            print("   請指定 --screenshot 或使用 --live")
            sys.exit(1)

    # 執行 template matching
    template = cv2.imread(crop_path, cv2.IMREAD_COLOR)
    screen_img = cv2.imread(test_screenshot, cv2.IMREAD_COLOR)
    if template is None or screen_img is None:
        print("❌ 無法讀取圖片")
        sys.exit(1)

    th, tw = template.shape[:2]
    sh, sw = screen_img.shape[:2]
    if th > sh or tw > sw:
        print(f"❌ Template ({tw}x{th}) 大於截圖 ({sw}x{sh})，無法比對")
        sys.exit(1)

    result_map = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result_map)
    conf = float(max_val)
    thr  = args.threshold
    passed = conf >= thr
    cx = max_loc[0] + tw // 2
    cy = max_loc[1] + th // 2

    # 建立 validation_result record
    val_id = _make_id("vr")
    val_record = {
        "id":             val_id,
        "created_at":     _now_iso(),
        "candidate_id":   args.id,
        "method":         "live_test" if args.live else "offline_match",
        "test_screenshot": test_screenshot,
        "opencv_conf":    round(conf, 6),
        "threshold":      thr,
        "match_location": list(max_loc),
        "match_center":   [cx, cy],
        "passed":         passed,
        "validated_by":   "automated",
        "decision":       "validated" if passed else "rejected",
        "rejection_reason": None if passed else f"conf={conf:.4f} < threshold={thr}",
        "notes":          args.notes,
    }
    _append(_VALIDATIONS_FILE, val_record)

    # 更新 candidate status
    # 若已 promote（promoted_to 非空），不降級 status，只更新 validation_id
    existing = _find_by_id(_CANDIDATES_FILE, args.id) or {}
    already_promoted = bool(existing.get("promoted_to", ""))
    if already_promoted and not passed:
        print(f"  ⚠️  此 candidate 已 promote，REJECT 結果僅記錄，不降級 status")
        _update_record(_CANDIDATES_FILE, args.id, {"validation_id": val_id})
    else:
        new_status = "validated" if passed else "rejected"
        _update_record(_CANDIDATES_FILE, args.id, {
            "status":        new_status,
            "validation_id": val_id,
        })

    print(SEP)
    print(f"[validate-template] {'✅ PASSED' if passed else '❌ REJECTED'}")
    print(f"  Candidate ID  : {args.id}")
    print(f"  Template      : {crop_path}")
    print(f"  Screenshot    : {test_screenshot}")
    print(f"  OpenCV conf   : {conf:.4f}  (threshold={thr})")
    print(f"  Match center  : ({cx}, {cy})")
    print(f"  Validation ID : {val_id}")
    print(f"  Status        : {new_status}")
    print(SEP)

    if passed:
        print(f"\n下一步（promote 到 assets/）：")
        print(f"  python tools/template_discovery.py promote-template --id {args.id} \\")
        print(f"      --to experiments/ad_closer/assets/ad_close/")
    else:
        print(f"\n  Conf={conf:.4f} 低於 threshold={thr}，template 可能需要重新裁切。")
        print(f"  提示：若 conf 介於 0.5~0.8，嘗試調低 --threshold 或重新 crop。")


# ── promote-template ──────────────────────────────────────────────

def cmd_promote_template(args: argparse.Namespace) -> None:
    """
    將已驗證的 candidate crop 複製到指定的 assets/ 目錄，
    並更新 template_library index。
    只有 status=validated 的 candidate 才能 promote。
    """
    _ensure_dirs()

    record = _find_by_id(_CANDIDATES_FILE, args.id)
    if record is None:
        print(f"❌ 找不到 candidate: {args.id!r}")
        sys.exit(1)

    if record.get("status") != "validated":
        print(f"❌ Candidate status={record.get('status')!r}，"
              f"只有 validated 才能 promote")
        print("   請先執行 validate-template")
        sys.exit(1)

    crop_path = record.get("crop_path", "")
    if not crop_path or not os.path.exists(crop_path):
        print(f"❌ Crop 不存在: {crop_path!r}")
        sys.exit(1)

    # 決定目標路徑
    dest_dir = os.path.abspath(args.to)
    os.makedirs(dest_dir, exist_ok=True)

    filename = args.filename or f"{record.get('target_label', 'template')}.png"
    if not filename.endswith(".png"):
        filename += ".png"
    dest_path = os.path.join(dest_dir, filename)

    if os.path.exists(dest_path) and not args.overwrite:
        print(f"❌ 目標已存在: {dest_path!r}")
        print("   使用 --overwrite 強制覆蓋")
        sys.exit(1)

    shutil.copy2(crop_path, dest_path)

    # 更新 candidate record
    _update_record(_CANDIDATES_FILE, args.id, {"promoted_to": dest_path})

    # 建立 template_library record
    lib_id = _make_id("tl")
    lib_record = {
        "id":                lib_id,
        "created_at":        _now_iso(),
        "label":             record.get("label", ""),
        "target_label":      record.get("target_label", ""),
        "filename":          filename,
        "assets_path":       dest_path,
        "screen_type":       record.get("screen_type", ""),
        "source":            record.get("source", ""),
        "candidate_id":      args.id,
        "validation_id":     record.get("validation_id", ""),
        "status":            "validated",
        "notes":             args.notes,
    }
    _append(_LIBRARY_FILE, lib_record)

    print(SEP)
    print(f"[promote-template] ✅ Promote 完成")
    print(f"  Candidate ID  : {args.id}")
    print(f"  Source        : {crop_path}")
    print(f"  Destination   : {dest_path}")
    print(f"  Library ID    : {lib_id}")
    print(SEP)
    print(f"\n✅ Template 已加入 library，下次 OpenCV 會自動使用：")
    print(f"   {dest_path}")


# ── list-candidates ───────────────────────────────────────────────

def cmd_list_candidates(args: argparse.Namespace) -> None:
    """列出所有候選 template，支援 status / screen_type 篩選。"""
    _ensure_dirs()

    records = _load_all(_CANDIDATES_FILE)

    if args.status:
        records = [r for r in records if r.get("status") == args.status]
    if args.screen_type:
        records = [r for r in records if r.get("screen_type") == args.screen_type]
    if args.source_module:
        # 透過 pending_id 找 source_module
        pendings = {p["id"]: p for p in _load_all(_PENDING_FILE)}
        records = [
            r for r in records
            if pendings.get(r.get("pending_id", ""), {}).get("source_module") == args.source_module
        ]

    if not records:
        print("（無候選 template）")
        return

    # 載入 validation conf
    validations = {v["candidate_id"]: v for v in _load_all(_VALIDATIONS_FILE)}

    print(SEP)
    print(f"{'ID':<32}  {'Label':<22}  {'Screen Type':<18}  {'Status':<12}  {'Conf':>6}  {'Source':<8}")
    print("─" * 105)
    for r in records:
        vid   = r.get("id", "")[:32]
        label = (r.get("label", "") or "")[:22]
        stype = (r.get("screen_type", "") or "")[:18]
        status= (r.get("status", "") or "")[:12]
        src   = (r.get("source", "") or "")[:8]
        v     = validations.get(r.get("id", ""), {})
        conf_str = f"{v.get('opencv_conf', 0):.4f}" if v else "  N/A"
        print(f"{vid:<32}  {label:<22}  {stype:<18}  {status:<12}  {conf_str:>6}  {src:<8}")
    print(SEP)
    print(f"共 {len(records)} 筆")


# ── ai-analyze ────────────────────────────────────────────────────

def cmd_ai_analyze(args: argparse.Namespace) -> None:
    """
    使用 Edge CDP 把 pending_analysis 的截圖送給 AI 分析，
    自動建立 ai_analysis_result 與多個 candidate_templates record。

    注意：AI 結果只進 candidate，不會自動 promote。
    """
    _ensure_dirs()

    # 載入 pending record
    pending = _find_by_id(_PENDING_FILE, args.pending_id)
    if pending is None:
        print(f"❌ 找不到 pending_analysis: {args.pending_id!r}")
        sys.exit(1)

    screenshot = pending["screenshot_path"]
    target_hint = pending.get("target_hint", "close_button")
    screen_type = pending.get("screen_type", "unknown")

    print(SEP)
    print(f"[ai-analyze] 開始 AI 分析")
    print(f"  Pending ID    : {args.pending_id}")
    print(f"  Screenshot    : {screenshot}")
    print(f"  Provider      : {args.provider}")
    print(f"  Target hint   : {target_hint}")
    print(f"  Screen type   : {screen_type}")
    print(SEP)

    # 動態 import edge_cdp_ai（避免在 import 時就初始化）
    sys.path.insert(0, _THIS_DIR)
    try:
        from edge_cdp_ai import EdgeCdpAiAnalyzer, CdpStatus, check_cdp, print_cdp_startup_hint
    except ImportError as e:
        print(f"❌ 無法 import edge_cdp_ai: {e}")
        print("   請確認 tools/edge_cdp_ai.py 存在且 playwright 已安裝")
        sys.exit(1)

    # 執行分析
    analyzer = EdgeCdpAiAnalyzer(
        provider=args.provider,
        log_dir=os.path.join(_DATA_DIR, "ai_logs"),
    )
    result = analyzer.analyze(
        screenshot_path=screenshot,
        target_hint=target_hint,
        screen_type=screen_type,
    )

    # 更新 pending status
    _update_record(_PENDING_FILE, args.pending_id, {
        "status": "done" if result.status == CdpStatus.READY else f"error:{result.status.value}",
    })

    # 儲存 ai_analysis_result
    ai_result_id = _make_id("ar")
    ai_record = {
        "id":              ai_result_id,
        "created_at":      _now_iso(),
        "pending_id":      args.pending_id,
        "provider":        args.provider,
        "status":          result.status.value,
        "error":           result.error,
        "session_id":      result.session_id,
        "log_path":        result.log_path,
        "elapsed_seconds": result.elapsed_seconds,
        "parse_ok":        result.parsed is not None,
        "raw_response_preview": result.raw_response[:200] if result.raw_response else "",
        "parsed":          result.parsed,
    }
    _append(_AI_RESULTS_FILE, ai_record)

    # 若解析失敗，結束
    if result.status == CdpStatus.PARSE_FAILED:
        print(f"\n[ai-analyze] ⚠️  AI 回覆不是有效 JSON")
        print(f"  Raw response 已保存到: {result.log_path}")
        print(f"  AI result record: {ai_result_id}")
        print(f"\n  你可以手動讀取 log 並用 add-candidate 建立候選：")
        print(f"  python tools/template_discovery.py add-candidate \\")
        print(f"      --pending-id {args.pending_id} \\")
        print(f"      --label close_button \\")
        print(f"      --bbox x1,y1,x2,y2 \\")
        print(f"      --source human")
        return

    if result.status != CdpStatus.READY or result.parsed is None:
        print(f"\n[ai-analyze] ❌ 分析失敗：{result.status.value} — {result.error}")
        if result.status in (CdpStatus.UNAVAILABLE_NO_CDP,):
            print_cdp_startup_hint()
        return

    # 從 parsed candidates 建立 candidate_templates records
    candidates = result.parsed.get("candidates", [])
    created_ids = []

    for i, cand in enumerate(candidates):
        bbox_raw = cand.get("bbox", [])
        center_raw = cand.get("center", [])

        if len(bbox_raw) != 4:
            print(f"[ai-analyze] ⚠️  candidates[{i}] bbox 格式錯誤，跳過")
            continue

        x1, y1, x2, y2 = [int(v) for v in bbox_raw]
        cx = int(center_raw[0]) if len(center_raw) >= 2 else (x1 + x2) // 2
        cy = int(center_raw[1]) if len(center_raw) >= 2 else (y1 + y2) // 2

        rec_id = _make_id("ct")
        rec = {
            "id":               rec_id,
            "created_at":       _now_iso(),
            "pending_id":       args.pending_id,
            "ai_result_id":     ai_result_id,
            "label":            cand.get("label", "unknown"),
            "target_label":     cand.get("label", "unknown").replace(" ", "_"),
            "source_screenshot": screenshot,
            "crop_path":        "",
            "bbox":             {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "center":           [cx, cy],
            "screen_type":      screen_type,
            "source":           "ai",
            "status":           "candidate",
            "validation_id":    "",
            "promoted_to":      "",
            "confidence_note":  cand.get("confidence_note", ""),
            "risk_note":        cand.get("risk_note", ""),
            "notes":            f"AI rank {i+1}",
        }
        _append(_CANDIDATES_FILE, rec)
        created_ids.append(rec_id)

    print(SEP)
    print(f"[ai-analyze] ✅ 分析完成")
    print(f"  AI Result ID  : {ai_result_id}")
    print(f"  Status        : {result.parsed.get('status', 'unknown')}")
    print(f"  Candidates    : {len(created_ids)} 筆")
    for cid in created_ids:
        print(f"    → {cid}")
    print(SEP)

    if created_ids:
        print(f"\n下一步（裁切第一個候選）：")
        print(f"  python tools/template_discovery.py crop-candidate --id {created_ids[0]}")
    else:
        print(f"\n  AI 未找到候選元素（status={result.parsed.get('status')}）")
        print(f"  可考慮改用 add-candidate 手動建立")


# ══════════════════════════════════════════════════════════════════
# CLI 定義
# ══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="template_discovery.py",
        description=(
            "Template Discovery 工具\n"
            "把 debug screenshot 轉換為 validated OpenCV template。\n"
            "此工具與主線 bot 完全分離，不被 run_ad_closer.py import。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
完整工作流程：
  1. python tools/template_discovery.py discover-template \\
         --screenshot experiments/ad_closer/debug/failed_xxx.png \\
         --screen-type ad_endcard --target close_button

  2. python tools/template_discovery.py ai-analyze \\
         --pending-id pa_xxx --provider chatgpt

  3. python tools/template_discovery.py crop-candidate --id ct_xxx

  4. python tools/template_discovery.py validate-template --id ct_xxx \\
         --screenshot screenshots/current.png

  5. python tools/template_discovery.py promote-template --id ct_xxx \\
         --to experiments/ad_closer/assets/ad_close/
        """,
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # ── discover-template ─────────────────────────────────────────
    p = sub.add_parser("discover-template", help="登記 debug screenshot 為待分析記錄")
    p.add_argument("--screenshot", required=True, help="Debug screenshot 路徑")
    p.add_argument("--target", default="close_button",
                   help="目標元素 hint（預設: close_button）")
    p.add_argument("--screen-type", dest="screen_type", default="unknown",
                   help="截圖類型（ad_interstitial / ad_endcard / unknown 等）")
    p.add_argument("--source-module", dest="source_module", default="ad_closer",
                   help="產生截圖的模組（預設: ad_closer）")
    p.add_argument("--reason", default="MANUAL",
                   help="觸發原因（FAILED_TIMEOUT / CONF_TOO_LOW / MANUAL）")
    p.add_argument("--best-conf", dest="best_conf", type=float, default=0.0,
                   help="bot 看到的最高 confidence（參考用）")
    p.add_argument("--notes", default="", help="備註")

    # ── add-candidate ─────────────────────────────────────────────
    p = sub.add_parser("add-candidate", help="手動新增候選 template（已知 bbox）")
    p.add_argument("--pending-id", dest="pending_id", default="",
                   help="關聯的 pending_analysis ID（可選）")
    p.add_argument("--screenshot", default="",
                   help="截圖路徑（若未指定 pending-id 則必填）")
    p.add_argument("--label", required=True,
                   help="元素標籤，例如 close_button / skip_button")
    p.add_argument("--target-label", dest="target_label", default="",
                   help="建議的 assets/ 檔名（不含副檔名，預設同 label）")
    p.add_argument("--bbox", required=True,
                   help="BBox 格式 x1,y1,x2,y2（左上、右下）")
    p.add_argument("--screen-type", dest="screen_type", default="unknown")
    p.add_argument("--source", default="human", choices=["human", "ai", "manual"])
    p.add_argument("--notes", default="")

    # ── crop-candidate ────────────────────────────────────────────
    p = sub.add_parser("crop-candidate", help="根據 bbox 裁切 template 圖片")
    p.add_argument("--id", required=True, help="Candidate template ID（ct_xxx）")
    p.add_argument("--padding", type=int, default=4, help="四周各留幾 px 邊距（預設: 4）")
    p.add_argument("--preview", action="store_true", help="裁切後用系統開啟預覽")

    # ── validate-template ─────────────────────────────────────────
    p = sub.add_parser("validate-template", help="OpenCV 驗證候選 template")
    p.add_argument("--id", required=True, help="Candidate template ID（ct_xxx）")
    p.add_argument("--screenshot", default="", help="測試截圖路徑（不用 --live 時必填）")
    p.add_argument("--threshold", type=float, default=0.82,
                   help="OpenCV 信心值閾值（預設: 0.82）")
    p.add_argument("--live", action="store_true",
                   help="直接對模擬器即時截圖（需要 ADB 連線）")
    p.add_argument("--serial", default="127.0.0.1:5555",
                   help="ADB serial（--live 時使用）")
    p.add_argument("--notes", default="")

    # ── promote-template ──────────────────────────────────────────
    p = sub.add_parser("promote-template", help="將已驗證的 template 複製到 assets/")
    p.add_argument("--id", required=True, help="Candidate template ID（ct_xxx）")
    p.add_argument("--to", required=True,
                   help="目標目錄，例如 experiments/ad_closer/assets/ad_close/")
    p.add_argument("--filename", default="",
                   help="目標檔名（預設: target_label.png）")
    p.add_argument("--overwrite", action="store_true", help="若已存在則覆蓋")
    p.add_argument("--notes", default="")

    # ── list-candidates ───────────────────────────────────────────
    p = sub.add_parser("list-candidates", help="列出所有候選 template")
    p.add_argument("--status", default="",
                   help="篩選 status（candidate / validated / rejected / promoted）")
    p.add_argument("--screen-type", dest="screen_type", default="")
    p.add_argument("--source-module", dest="source_module", default="")

    # ── ai-analyze ────────────────────────────────────────────────
    p = sub.add_parser("ai-analyze",
                       help="Edge CDP AI 分析（需要 Edge CDP + playwright）")
    p.add_argument("--pending-id", dest="pending_id", required=True,
                   help="Pending analysis ID（pa_xxx）")
    p.add_argument("--provider", default="chatgpt",
                   choices=["chatgpt", "gemini"],
                   help="AI 平台（預設: chatgpt）")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "discover-template": cmd_discover_template,
        "add-candidate":     cmd_add_candidate,
        "crop-candidate":    cmd_crop_candidate,
        "validate-template": cmd_validate_template,
        "promote-template":  cmd_promote_template,
        "list-candidates":   cmd_list_candidates,
        "ai-analyze":        cmd_ai_analyze,
    }
    fn = dispatch.get(args.subcommand)
    if fn:
        fn(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
