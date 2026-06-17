"""
utils/ — 共用工具層

與 src_v2 和 ads2 共用，提供：
  - image_io.py：讀寫/標註圖片
  - crop_tool.py：偵測藍框、裁切 ROI
  - paint_launcher.py：開小畫家、等待關閉
  - archive.py：截圖歸檔、session 清理

設計原則：
  - 此層不依賴 src/ 或 src_v2/ 的任何模組（純工具）
  - 只依賴 opencv-python / numpy / pathlib 等標準套件
"""
