"""
src_v2 — 重構版執行層

目的：取代 src/ 的 task 執行層，解決以下問題：
  1. 各 task 各自 copy _match_task_asset / _tap_task_asset 的 boilerplate
  2. return_to_daily_tasks 有多種不同做法
  3. debug 截圖分散、無統一管理
  4. 底層工具（裁切、歸檔）重複實作

底層基礎設施仍從 src/ import：
  adb_controller, vision_matcher, config, exceptions,
  scene_detector, battle_handler, debug_log,
  daily_task_finder, navigator

src/ 保持凍結，不做任何修改。
"""
